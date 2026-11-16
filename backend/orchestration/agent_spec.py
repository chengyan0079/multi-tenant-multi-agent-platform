"""AgentSpec：统一入口的 Agent 规格（纯数据，不 import agents/* 以防循环依赖）。"""
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
    agent_type: str  # 业务唯一键
    display_name: str = ""  # 展示名
    description: str = ""  # 说明
    version: str = "1.0.0"  # 版本

    # 意图识别
    intent_labels: tuple[str, ...] = ()  # 意图标签
    intent_examples: tuple[str, ...] = ()  # 意图示例
    intent_hint: str = ""  # 意图提示
    default_agent: bool = False  # 是否为分类兜底 Agent

    # 权限
    resource: str = ""  # 资源名
    scope: str = ""  # 调用所需 scope
    menu_scope: str = ""  # 菜单可见 scope

    # 卡片与入口
    card: AgentCard | None = None  # 卡片配置
    templates: tuple[str, ...] = ()  # 模板问题
    entry_fields: tuple[EntryField, ...] = ()  # 入口表单字段
    accept_files: tuple[str, ...] = ()  # 支持的文件后缀

    # 执行
    execution_mode: Literal["stream", "task", "clarify", "pipeline"] = "stream"  # 执行模式
    adapter: str | None = None  # 事件适配器
    checkpoint_scope: bool = True  # checkpoint 分区：True=按业务实例，False=按轮次
    progress_labels: tuple[ProgressLabel, ...] = ()  # 进度标签
    generate_nodes: tuple[str, ...] = ()  # 生成类节点
    done_fields: tuple[str, ...] = ()  # 完成态字段
    init_prompt: str = ""  # 初始化提示词

    # 交互
    guidance_message: str = ""  # 引导文案
    guidance_action_label: str = ""  # 引导按钮文案
    route_key: str = ""  # 结果页路由键
    pipeline_steps: tuple[PipelineStep, ...] = ()  # 串联步骤

    # 菜单 / 观测 / 记忆
    menu: MenuSpec | None = None  # 菜单配置
    tags: tuple[str, ...] = ()  # 观测 tags
    trace_name: str = ""  # trace 名称
    summary_policy: str = "default"  # 摘要策略
    short_term_limit: int = 20  # 短期记忆条数上限
    long_term_blocks: tuple[str, ...] = ("summary", "fact", "preference")  # 长期记忆块


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
