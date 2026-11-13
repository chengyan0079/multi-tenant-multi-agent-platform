"""统一入口运行期配置构造：把 thread_id / trace_id / spec 观测字段并入 LangChain config。"""
from __future__ import annotations

from typing import Optional

from langchain_core.runnables import RunnableConfig

from backend.orchestration.agent_spec import AgentSpec
from backend.observability.tracing import tracing


def build_run_config(
    *,
    thread_id: str,
    trace_id: str,
    spec: AgentSpec,
    callbacks: Optional[list] = None,
) -> RunnableConfig:
    """构造一次调用所需的 LangChain config，注入统一入口观测元数据与 tags。"""
    base: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "metadata": {
            "trace_id": trace_id,
            "source": "unified",
            "agent_type": spec.agent_type,
            "spec_version": spec.version,
        },
        "tags": list(spec.tags) + ["unified"],
    }
    if callbacks:
        base["callbacks"] = list(callbacks)
    return tracing.with_callbacks(base)
