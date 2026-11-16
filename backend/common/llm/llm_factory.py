"""四模型统一工厂：LLM/嵌入/重排/意图分类，按配置构造并缓存，支持按 agent 解析。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, List, Optional, Type

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from backend.app_state import app_state
from backend.common.logger import get_logger
from backend.data.dao.agent.agent_model_rel_dao import AgentModelRelDao
from backend.data.dao.agent.model_dao import ModelDao
from backend.observability.exception import ModelError

logger = get_logger("llm_factory")


def _resolve_endpoint_path(endpoint_path: Optional[str]) -> Optional[str]:
    """把 registry 的 endpoint_path 解析为可加载的本地路径。

    - None/空 → 返回 None（调用方回退 name，走 HuggingFace 在线加载）；
    - 绝对路径 → 原样返回；
    - 相对路径 → 拼到配置 MODEL_ROOT（默认项目根）下再解析。
    解析后路径不存在则抛出清晰错误（含绝对路径与来源），便于排查。
    """
    from backend.config.settings import config

    if not endpoint_path:
        return None
    p = Path(endpoint_path)
    if not p.is_absolute():
        p = Path(config.model.root) / endpoint_path
    p = p.resolve()
    if not p.exists():
        raise ModelError(
            f"本地模型路径不存在：{p}（endpoint_path={endpoint_path!r}，MODEL_ROOT={config.model.root!r}）"
        )
    return str(p)


class LLMFactory:
    """模型工厂单例：集中构造与缓存 LLM / Embedding / Reranker / Classifier。

    缓存 key：
      - 全局重模型：embedding / reranker / classifier（ModelManager 启动预加载常驻）
      - per-agent LLM：llm:<agent_type>（首次调用时解析并缓存，配置变更由 reload() 失效）
    """

    def __init__(self) -> None:
        # 全局默认 LLM（业务侧占位/向后兼容用）；per-agent 走 get_llm(agent_type)
        self._llm: Optional[BaseChatModel] = None
        # 所有缓存客户端
        self._cache: dict[str, Any] = {}

    # ---------- 纯构造（由配置 dict 构造客户端，不碰 DB） ----------

    @staticmethod
    def build_llm(cfg: dict[str, Any], *, thinking: bool = False) -> BaseChatModel:
        """构造 OpenAI 兼容聊天模型（model_registry 的 llm 记录 → ChatOpenAI）。

        thinking=True 时透传 extra_body（默认 {"thinking": {"type": "enabled"}}，
        可用 QA_THINKING_EXTRA_BODY 覆盖），让支持推理的模型输出思考过程。
        """
        import json

        from langchain_openai import ChatOpenAI

        extra: dict[str, Any] = {}
        if thinking:
            from backend.config import config

            raw = getattr(config.qa, "thinking_extra_body", "") or '{"thinking":{"type":"enabled"}}'
            try:
                extra["extra_body"] = json.loads(raw)
            except (ValueError, TypeError):
                extra["extra_body"] = {"thinking": {"type": "enabled"}}

        return ChatOpenAI(
            model=cfg["name"],
            api_key=cfg.get("api_key") or "EMPTY",
            base_url=cfg.get("base_url"),
            temperature=cfg["temperature"] if cfg["temperature"] is not None else 0.2,
            timeout=cfg["timeout_s"] if cfg["timeout_s"] is not None else 60,
            max_retries=cfg["max_retries"] if cfg["max_retries"] is not None else 2,
            # 流式输出最后一个 chunk 带 token usage，供问答结果/agent_run 统计
            stream_usage=True,
            **extra,
        )

    @staticmethod
    def build_embedder(cfg: dict[str, Any]) -> Any:
        """构造 bge-m3 嵌入函数（重模型，加载较慢）。

        优先用 model_registry.endpoint_path（本地权重目录，离线可用；相对路径会拼到
        MODEL_ROOT 下解析，见 _resolve_endpoint_path），缺省才回退 name（HF 仓库名，会联网拉取）。
        与 classifier 的本地加载一致。
        """
        from milvus_model.hybrid import BGEM3EmbeddingFunction

        model_ref = _resolve_endpoint_path(cfg.get("endpoint_path")) or cfg["name"]
        return BGEM3EmbeddingFunction(model_name=model_ref)

    @staticmethod
    def build_reranker(cfg: dict[str, Any]) -> Any:
        """构造 bge-reranker 精排函数（重模型）。

        同 build_embedder：优先 endpoint_path 本地目录（相对路径拼 MODEL_ROOT），缺省回退 name。
        """
        from milvus_model.reranker import BGERerankFunction

        model_ref = _resolve_endpoint_path(cfg.get("endpoint_path")) or cfg["name"]
        return BGERerankFunction(model_name=model_ref)

    @staticmethod
    def build_classifier(cfg: dict[str, Any]) -> tuple[Any, Any, list, int]:
        """按 classifier.endpoint_path 加载离线意图分类产物（HF 格式）。

        labels / max_len 解析优先级（meta.json 不再强制）：
          - 目录含 meta.json         → 以它为准（兼容已有产物）；
          - 否则含 label_mapping.json → 按 {标签名: 索引} 取索引升序得到 labels；
          - 否则 model.config.id2label → 按索引顺序拼标签；
          - 都没有                   → 退化为数值标签 list(range(num_labels))。
        max_len：meta.json 优先，缺省 64。
        endpoint_path 为相对路径时拼 MODEL_ROOT 解析（见 _resolve_endpoint_path）。
        """
        endpoint_path = _resolve_endpoint_path(cfg.get("endpoint_path"))
        if not endpoint_path:
            raise ModelError("意图分类器未配置 endpoint_path（model_registry 的 classifier 记录）")
        import json as _json

        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        d = Path(endpoint_path)
        tokenizer = AutoTokenizer.from_pretrained(d)
        model = AutoModelForSequenceClassification.from_pretrained(d)
        model.eval()

        labels: list
        max_len: int = 64
        meta_path = d / "meta.json"
        mapping_path = d / "label_mapping.json"
        if meta_path.exists():
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
            labels = meta["labels"]
            max_len = int(meta.get("max_len", 64))
        elif mapping_path.exists():
            mapping = _json.loads(mapping_path.read_text(encoding="utf-8"))
            # {标签名: 索引} → 按索引升序，使 labels[索引] = 标签名
            labels = [name for name, _ in sorted(mapping.items(), key=lambda kv: kv[1])]
        else:
            id2label = getattr(model.config, "id2label", None)
            if id2label:
                labels = [id2label[str(i)] for i in range(len(id2label))]
            else:
                num_labels = int(getattr(model.config, "num_labels", 0) or 0)
                labels = list(range(num_labels))
        return model, tokenizer, labels, max_len

    # ---------- 缓存管理（供 ModelManager 预加载 / 失效） ----------

    def cache_client(self, key: str, client: Any) -> None:
        """写入一条缓存客户端（ModelManager 预加载全局重模型用）。"""
        self._cache[key] = client

    def get_cached(self, key: str) -> Any:
        return self._cache.get(key)

    def clear_llm_cache(self) -> None:
        """失效所有 per-agent LLM 缓存（agent_model / model_registry 变更后调用）。"""
        self._cache = {k: v for k, v in self._cache.items() if not k.startswith("llm:")}

    def clear_cache(self) -> None:
        """清空全部缓存（registry 变更后重载用）。"""
        self._cache = {}

    # ---------- 全局默认 LLM（向后兼容） ----------

    @property
    def llm(self) -> BaseChatModel:
        if self._llm is None:
            raise ModelError("LLM 未初始化（检查 model_registry 的 llm 配置 / API_KEY/API_BASE）")
        return self._llm

    # ---------- per-agent 解析 ----------

    async def get_llm(
        self, agent_type: str, model_type: str = "llm", *, thinking: bool = False
    ) -> BaseChatModel:
        """按 agent 解析并缓存其 LLM 客户端。

        解析顺序：agent_model 绑定（is_default/priority）→ 无绑定回退 model_registry 的
        active；配置变更后调用 clear_llm_cache() 使其下次重新解析。
        thinking=True 时使用单独的缓存 key（不污染普通模式客户端）。
        """
        key = f"{model_type}:{agent_type}:thinking" if thinking else f"{model_type}:{agent_type}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        cfg = await AgentModelRelDao.resolve(agent_type, model_type) or await ModelDao.get_active(
            model_type
        )
        if not cfg:
            raise ModelError(
                f"无可用 {model_type} 模型（agent={agent_type} 无绑定且 model_registry 无 active）"
            )
        client = self.build_llm(cfg, thinking=thinking)
        self._cache[key] = client
        return client

    async def get_structured_llm(
        self, agent_type: str, schema: Any, model_type: str = "llm"
    ) -> Any:
        """返回结构化输出包装器。

        不用 with_structured_output(function_calling)：当前 MaaS 会拒绝带 tools 的请求
        （400001）。改为普通 chat + JSON Schema 指令 + 解析重试，兼容性更好。
        """
        llm = await self.get_llm(agent_type, model_type)
        return StructuredLLM(llm, schema)

    # ---------- 全局模型（embed/rerank/classify，由 ModelManager 预加载） ----------

    async def embed(self, texts: List[str], *, query: bool = False) -> dict:
        """bge-m3 向量化，返回 {'dense': [...], 'sparse': [...]}。

        milvus_model 的 BGEM3EmbeddingFunction 只暴露 encode_documents / encode_queries，
        不再有 encode；这里按用途选择，并兼容旧版仅有 encode 的实现。
        """
        embedder = self._cache.get("embedding")
        if embedder is None:
            cfg = await ModelDao.get_active("embedding")
            if not cfg:
                raise ModelError("Embedding 未配置（model_registry 无 enabled 的 embedding 记录）")
            embedder = self.build_embedder(cfg)
            self._cache["embedding"] = embedder
        encoder = getattr(embedder, "encode", None)
        if encoder is None:
            encoder = getattr(
                embedder,
                "encode_queries" if query else "encode_documents",
                None,
            )
        if encoder is None:
            raise ModelError("Embedding 模型不支持 encode / encode_documents / encode_queries")
        return await asyncio.to_thread(encoder, texts)

    async def rerank(self, query: str, documents: List[str], top_n: int = 5) -> List[float]:
        """bge-reranker-v2-m3 精排，返回与 documents 对齐的相关性分数。"""
        reranker = self._cache.get("reranker")
        if reranker is None:
            cfg = await ModelDao.get_active("reranker")
            if not cfg:
                raise ModelError("Reranker 未配置（model_registry 无 enabled 的 reranker 记录）")
            reranker = self.build_reranker(cfg)
            self._cache["reranker"] = reranker
        # 明确使用 milvus_model.BGERerankFunction：
        #   __call__(query, documents, top_k=5) —— 必须传 top_k=len(documents)，
        #   否则默认只给前 5 个候选打分，其余分数缺失会导致排序错乱。
        result = await asyncio.to_thread(
            reranker, query=query, documents=documents, top_k=len(documents)
        )
        return self._align_rerank_scores(result, len(documents))

    @staticmethod
    def _align_rerank_scores(result: List[Any], n: int) -> List[float]:
        """把 BGERerankFunction 的 `RerankResult(text, score, index)` 列表按 index 对齐。

        - 只做**结构对齐**（放回 documents 原位置），不做数值归一化；
        - normalize=True 时 score 是 sigmoid 0~1，原样返回。
        """
        out = [0.0] * n
        for item in result or []:
            idx = getattr(item, "index", None)
            score = getattr(item, "score", 0.0)
            if isinstance(idx, int) and 0 <= idx < n:
                out[idx] = float(score)
        return out

    async def classify(self, text: str) -> str:
        """bert-chinese 中文意图分类；未配置或加载失败降级为 'general'。"""
        bundle = self._cache.get("classifier")
        if bundle is None:
            cfg = await ModelDao.get_active("classifier")
            if not cfg or not cfg.get("endpoint_path"):
                return "general"
            try:
                bundle = self.build_classifier(cfg)
            except Exception as exc:
                logger.exception(f"意图分类器加载跳过（将以 general 兜底）: {exc}")
                return "general"
            self._cache["classifier"] = bundle
        model, tokenizer, labels, max_len = bundle
        return await asyncio.to_thread(self._classify_one, model, tokenizer, labels, max_len, text)

    @staticmethod
    def _classify_one(model, tokenizer, labels: list, max_len: int, text: str) -> str:
        import torch

        enc = tokenizer(
            text, return_tensors="pt", truncation=True, padding="max_length", max_length=max_len
        )
        with torch.no_grad():
            logits = model(**enc).logits
        idx = int(logits.argmax(dim=-1).item())
        return labels[idx] if 0 <= idx < len(labels) else "general"

    async def stop(self) -> None:
        self._llm = None
        self._cache = {}


class StructuredLLM:
    """把普通聊天模型包装成结构化输出：显式给 JSON Schema，解析失败自动重试。

    不依赖 provider 的 tools/function_calling 或 response_format。
    """

    def __init__(self, llm: BaseChatModel, schema: Type[BaseModel], max_attempts: int = 2):
        self._llm = llm
        self._schema = schema
        self._max_attempts = max(1, max_attempts)

    def _schema_prompt(self) -> str:
        schema_json = json.dumps(self._schema.model_json_schema(), ensure_ascii=False)
        return (
            "请严格输出一个 JSON 对象，不要输出 Markdown 代码块、解释或任何前后缀。"
            "JSON 必须符合以下 JSON Schema：\n"
            f"{schema_json}"
        )

    def _with_schema(self, messages: list[Any]) -> list[Any]:
        instruction = self._schema_prompt()
        out = list(messages)
        if out and isinstance(out[0], SystemMessage):
            out[0] = SystemMessage(content=f"{out[0].content}\n\n{instruction}")
        else:
            out.insert(0, SystemMessage(content=instruction))
        return out

    @staticmethod
    def _content_text(response: Any) -> str:
        content = getattr(response, "content", response)
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    parts.append(str(part.get("text", "")))
                else:
                    parts.append(str(part))
            return "".join(parts)
        return str(content)

    def _parse(self, text: str) -> BaseModel:
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            if raw.rstrip().endswith("```"):
                raw = raw.rstrip()[:-3]
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < start:
            raise ValueError("输出中未找到 JSON 对象")
        data = json.loads(raw[start : end + 1])
        return self._schema.model_validate(data)

    async def ainvoke(self, messages: list[Any], config: Any = None, **kwargs: Any) -> BaseModel:
        base = self._with_schema(messages)
        last_error: Exception | None = None
        last_text = ""
        for attempt in range(self._max_attempts):
            response = await self._llm.ainvoke(base, config=config, **kwargs)
            last_text = self._content_text(response)
            try:
                return self._parse(last_text)
            except Exception as exc:  # noqa: BLE001 - 解析失败用修复提示重试
                last_error = exc
                if attempt + 1 >= self._max_attempts:
                    break
                base = self._with_schema(messages) + [
                    AIMessage(content=last_text),
                    HumanMessage(
                        content=(
                            "上一条输出不是合法 JSON，错误："
                            f"{exc}。请只输出符合 JSON Schema 的 JSON 对象，不要解释。"
                        )
                    ),
                ]
        raise ValueError(
            f"结构化输出解析失败（{self._schema.__name__}）：{last_error}；"
            f"最后输出：{last_text[:500]}"
        )


async def get_llm(agent_type: str, *, thinking: bool = False) -> BaseChatModel:
    """按 agent 创建并缓存其 LLM 客户端（委托运行中的工厂单例）。

    thinking=True 时使用开启推理的客户端（extra_body 透传，见 build_llm）。
    单例由 ModelManager 启动预加载；未启动则报错，避免拿到空工厂。
    """
    factory = app_state.llm_factory
    if factory is None:
        raise ModelError("LLMFactory 未初始化（ModelManager 尚未完成启动）")
    return await factory.get_llm(agent_type, thinking=thinking)


async def get_structured_llm(agent_type: str, schema: Type[BaseModel]) -> Any:
    """按 agent 创建结构化输出包装器（JSON Schema + 解析重试）。

    底层为异步解析，调用方需 await。
    """
    factory = app_state.llm_factory
    if factory is None:
        raise ModelError("LLMFactory 未初始化（ModelManager 尚未完成启动）")
    return await factory.get_structured_llm(agent_type, schema)
