"""LLM Token 用量回调：汇总一次图执行中所有 LLM 调用的 usage。"""

from __future__ import annotations

import threading
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class TokenUsageCallback(AsyncCallbackHandler):
    """收集 prompt / completion / total tokens。

    同时兼容 OpenAI 风格 `token_usage` 和 LangChain `usage_metadata`：
    - prompt_tokens / completion_tokens / total_tokens
    - input_tokens / output_tokens / total_tokens
    流式输出需要 ChatOpenAI(stream_usage=True)，否则最后一个 chunk 可能没有 usage。
    """

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.llm_calls = 0
        self.errors = 0
        self.usage_available = False
        self.models: set[str] = set()
        self.last_error: str | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _model_name(serialized: dict[str, Any] | None, kwargs: dict[str, Any]) -> str | None:
        data = serialized or {}
        model_kwargs = data.get("kwargs") or {}
        invocation = kwargs.get("invocation_params") or {}
        for candidate in (
            model_kwargs.get("model_name"),
            model_kwargs.get("model"),
            invocation.get("model_name"),
            invocation.get("model"),
            invocation.get("_type"),
            data.get("name"),
        ):
            if candidate:
                return str(candidate)
        return None

    @staticmethod
    def _usage(response: LLMResult) -> dict[str, Any]:
        llm_output = response.llm_output or {}
        usage = llm_output.get("token_usage") or llm_output.get("usage") or {}

        for generation_list in response.generations or []:
            for generation in generation_list:
                message = getattr(generation, "message", None)
                metadata = getattr(message, "usage_metadata", None) or {}
                response_metadata = getattr(message, "response_metadata", None) or {}
                extra_usage = (
                    response_metadata.get("token_usage") or response_metadata.get("usage") or {}
                )
                if not usage and metadata:
                    usage = metadata
                if not usage and extra_usage:
                    usage = extra_usage
        return usage if isinstance(usage, dict) else {}

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any] | None,
        messages: list[list[Any]],
        **kwargs: Any,
    ) -> None:
        model = self._model_name(serialized, kwargs)
        if model:
            with self._lock:
                self.models.add(model)

    async def on_llm_start(
        self,
        serialized: dict[str, Any] | None,
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        model = self._model_name(serialized, kwargs)
        if model:
            with self._lock:
                self.models.add(model)

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        usage = self._usage(response)
        prompt = _int(
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or usage.get("input_token_count")
        )
        completion = _int(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or usage.get("output_token_count")
        )
        total = _int(usage.get("total_tokens")) or (prompt + completion)
        model = self._model_name(kwargs.get("serialized"), kwargs) or (
            (response.llm_output or {}).get("model_name")
        )
        with self._lock:
            self.llm_calls += 1
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            self.total_tokens += total
            if prompt or completion or total:
                self.usage_available = True
            if model:
                self.models.add(str(model))

    async def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        with self._lock:
            self.errors += 1
            self.last_error = str(error)[:500]

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
                "llm_calls": self.llm_calls,
                "models": sorted(self.models),
                "usage_available": self.usage_available,
                "errors": self.errors,
                "last_error": self.last_error,
            }
