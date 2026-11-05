"""模型工厂（LLM / bge-m3 / bge-reranker / bert-chinese）启动管理。

启动期负责：模型就绪自检 + 本地模型预加载 + 设置全局默认 LLM。
本地模型（provider=local）启动期即离线加载到内存（重模型）或构造客户端（本地 LLM），
避免首次调用懒加载阻塞；远程模型仍按需懒加载。per-agent LLM 由各 agent 调用时经
LLMFactory.get_llm(agent_type) 按需解析并缓存，配置（model_registry / agent_model）变更后
调用 reload() 失效缓存、重新预加载。
"""
from __future__ import annotations

import asyncio

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
        """就绪自检 + 本地模型预加载 + 设置全局默认 LLM。"""
        await ModelManager._check_ready()
        # 本地模型（provider=local）启动期预加载：重模型按 endpoint_path 离线加载到内存，
        # 本地 LLM 仅构造客户端；避免首次调用时懒加载阻塞或触发联网下载。
        await ModelManager._preload_local(factory)
        # 全局默认 LLM（active，任意 provider；业务侧占位/向后兼容用；per-agent 走 get_llm）
        # 构建失败即视为启动失败（fail-fast），不再静默置空，交由 AppServer 终止启动。
        llm_cfg = await ModelDao.get_active("llm")
        if llm_cfg is not None:
            logger.info(f"全局默认 LLM 预加载：{llm_cfg.get('name')}")
            factory._llm = factory.build_llm(llm_cfg)

    @staticmethod
    async def _preload_local(factory: LLMFactory) -> None:
        """预加载全部本地（provider=local）模型（fail-fast）。

        重模型（embedding/reranker/classifier）按 model_registry.endpoint_path 离线加载到
        内存并缓存；本地 LLM 仅构造客户端（vLLM / Ollama 等本地推理服务）。每类 active 本地
        模型同时挂到全局裸 key（embedding/reranker/classifier），使运行时 embed()/rerank()/
        classify() 直接走热路径，不再首次懒加载。

        行为：任一本地模型加载失败即视为启动失败——记录错误并抛出原始异常，由 AppServer.start_all
        捕获后终止启动并回滚已启动项（不再静默跳过），符合「启动 manager 有异常就停服务」策略。
        """
        rows = await ModelDao.list_by_provider("local")
        if not rows:
            logger.info("model_manager: 无本地（provider=local）模型，跳过预加载")
            return
        # 同类按 sort_order 最小的一条视作 active，用于挂全局裸 key
        active_by_type: dict[str, dict[str, Any]] = {}
        for cfg in rows:
            mt = cfg["model_type"]
            if mt not in active_by_type or cfg["sort_order"] < active_by_type[mt]["sort_order"]:
                active_by_type[mt] = cfg
            # 加载失败直接抛出（fail-fast）：交由 AppServer 终止启动，不再静默跳过
            try:
                client = await ModelManager._build_local(factory, cfg)
            except Exception as exc:
                logger.error(
                    f"本地模型预加载失败 {mt}/{cfg['name']}：{exc}（fail-fast，终止启动）"
                )
                raise
            factory.cache_client(f"local:{mt}:{cfg['name']}", client)
            logger.info(f"本地模型预加载完成：{mt}/{cfg['name']}（provider=local）")
        # 重模型挂全局裸 key，热路径免懒加载
        for mt in ("embedding", "reranker", "classifier"):
            cfg = active_by_type.get(mt)
            if cfg is None:
                continue
            cached = factory.get_cached(f"local:{mt}:{cfg['name']}")
            if cached is not None:
                factory.cache_client(mt, cached)
                logger.info(f"本地模型已挂载为全局 {mt}：{cfg['name']}")

    @staticmethod
    async def _build_local(factory: LLMFactory, cfg: dict[str, Any]) -> Any:
        """按 model_type 构造本地模型客户端（重模型放线程避免阻塞事件循环）。"""
        mt = cfg["model_type"]
        if mt in _GLOBAL_BUILDERS:
            return await asyncio.to_thread(_GLOBAL_BUILDERS[mt], factory, cfg)
        if mt == "llm":
            return factory.build_llm(cfg)
        raise ValueError(f"不支持预加载的模型类型: {mt}")

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
