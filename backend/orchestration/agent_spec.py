"""AgentSpec：统一入口的 Agent 规格（纯数据，不 import agents/* 以防循环依赖）。

各 Agent 在自身 agent.py 的 metadata() 返回 AgentSpec；AgentRegistry 在 load_from_db
时把 agent 表运营字段覆写进 spec，并在 _rebuild_derived 中派生路由/校验/权限等。
"""
from dataclasses import dataclass, replace
from typing import Literal

from backend.orchestration.unified_schemas import (
    AgentCard,
    EntryField,
    MenuSpec,
    PipelineStep,
    ProgressLabel,
)


@dataclass(frozen=True)
class AgentSpec:
    # 身份（可被 agent 表覆写）
    agent_type: str
    display_name: str = ""
    description: str = ""
    version: str = "1.0.0"

    # 意图识别
    intent_labels: tuple[str, ...] = ()
    intent_examples: tuple[str, ...] = ()
    intent_hint: str = ""
    default_agent: bool = False

    # 权限
    resource: str = ""
    scope: str = ""
    menu_scope: str = ""

    # 卡片与入口
    card: AgentCard | None = None
    templates: tuple[str, ...] = ()
    entry_fields: tuple[EntryField, ...] = ()
    accept_files: tuple[str, ...] = ()

    # 执行
    execution_mode: Literal["stream", "task", "clarify", "pipeline"] = "stream"
    adapter: str | None = None
    checkpoint_scope: bool = True
    progress_labels: tuple[ProgressLabel, ...] = ()
    generate_nodes: tuple[str, ...] = ()
    done_fields: tuple[str, ...] = ()
    init_prompt: str = ""

    # 交互
    guidance_message: str = ""
    guidance_action_label: str = ""
    route_key: str = ""
    pipeline_steps: tuple[PipelineStep, ...] = ()

    # 菜单 / 观测 / 记忆
    menu: MenuSpec | None = None
    tags: tuple[str, ...] = ()
    trace_name: str = ""
    summary_policy: str = "default"
    short_term_limit: int = 20
    long_term_blocks: tuple[str, ...] = ("summary", "fact", "preference")


def merge_db_overrides(
    spec: "AgentSpec",
    *,
    name: str | None,
    description: str | None,
    version: str | None,
) -> "AgentSpec":
    """把 agent 表运营字段覆写进 spec（仅运营字段，结构性字段随图包发版）。"""
    return replace(
        spec,
        display_name=name or spec.display_name,
        description=description or spec.description,
        version=version or spec.version,
    )
