"""模型工厂（LLM / bge-m3 / bge-reranker / bert-chinese）启动管理。

启动期负责：模型就绪自检 + 设置全局默认 LLM。
重模型（bge/bert 的 embedding/reranker/classifier）暂不启动预加载，改为首次使用时懒加载
（见 _preload 的 TODO）；per-agent LLM 由各 agent 调用时经 LLMFactory.get_llm(agent_type)
按需解析并缓存，配置（model_registry / agent_model）变更后调用 reload() 失效缓存、重新预加载。
"""
from __future__ import annotations

from typing import Any, Callable

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.common.llm.llm_factory import LLMFactory
from backend.data.dao.agent.model_dao import ModelDao
from backend.server.base_manager import BaseManager, HealthInfo

logger = get_logger("model_manager")

_MODEL_TYPES = ("llm", "embedding", "reranker", "classifier")

# 全局重模型（非 llm）按类型分派的构造器
_GLOBAL_BUILDERS: dict[str, Callable[[LLMFactory, dict[str, Any]], Any]] = {
    "embedding": lambda f, c: f.build_embedder(c),
    "reranker": lambda f, c: f.build_reranker(c),
    "classifier": lambda f, c: f.build_classifier(c),
}


class ModelManager(BaseManager):
    async def start(self) -> None:
        factory = LLMFactory()
        await self._preload(factory)
        app_state.llm_factory = factory

    async def reload(self) -> None:
        """配置（model_registry / agent_model）变更后重载：失效缓存并重新预加载。"""
        factory = app_state.llm_factory
        if factory is None:
            await self.start()
            return
        factory.clear_cache()
        await self._preload(factory)

    async def stop(self) -> None:
        if app_state.llm_factory is not None:
            await app_state.llm_factory.stop()
            app_state.llm_factory = None

    async def health(self) -> HealthInfo:
        if app_state.llm_factory is None:
            return HealthInfo(status="down", detail="llm_factory 未初始化")
        return HealthInfo(status="running")

    # ---------- 内部 ----------

    @staticmethod
    async def _preload(factory: LLMFactory) -> None:
        """就绪自检 + 设置全局默认 LLM（重模型改为懒加载，见下方 TODO）。"""
        await ModelManager._check_ready()
        # TODO(临时): embedding/reranker/classifier 启动期暂不预加载。
        #   原因：本地重模型（bge-m3 / bge-reranker）加载慢，且未配本地路径时会去
        #   HuggingFace 拉取导致启动阻塞；当前业务代码尚未真正调用 embed/rerank/classify。
        #   待接入后取消下面注释恢复常驻预加载（本地路径见 model_registry.endpoint_path）。
        # for mt in ("embedding", "reranker", "classifier"):
        #     cfg = await ModelDao.get_active(mt)
        #     if cfg is None:
        #         continue
        #     try:
        #         factory.cache_client(mt, _GLOBAL_BUILDERS[mt](factory, cfg))
        #     except Exception as exc:
        #         logger.warning(f"{mt} 预加载跳过: {exc}")
        # 全局默认 LLM（业务侧占位/向后兼容用；per-agent 走 get_llm）
        llm_cfg = await ModelDao.get_active("llm")
        if llm_cfg is not None:
            try:
                factory._llm = factory.build_llm(llm_cfg)
            except Exception as exc:
                logger.warning(f"全局 LLM 预加载跳过: {exc}")
                factory._llm = None

    @staticmethod
    async def _check_ready() -> None:
        """启动期就绪自检：四类在 model_registry 必须各至少一条 enabled=true，否则启动阻断。"""
        missing = []
        for mt in _MODEL_TYPES:
            try:
                n = await ModelDao.count_enabled(mt)
            except Exception as exc:
                raise RuntimeError(
                    f"模型就绪自检失败：无法查询 model_registry 的 {mt} 记录（DB 是否就绪？）: {exc}"
                ) from exc
            if n == 0:
                missing.append(mt)
        if missing:
            raise RuntimeError(
                "模型就绪自检未通过：以下类型在 model_registry 中无 enabled=true 记录，"
                f"启动阻断：{', '.join(missing)}"
            )
        logger.info("模型就绪自检通过：llm/embedding/reranker/classifier 均存在 enabled 记录")
