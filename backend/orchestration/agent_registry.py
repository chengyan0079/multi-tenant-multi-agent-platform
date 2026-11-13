"""Agent 注册/发现：启动注册 build_graph，元数据与开通策略入内存，运行期可 refresh。"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Optional

from backend.common.logger import get_logger
from backend.data.dao.agent.agent_dao import AgentDao
from backend.orchestration.agent_spec import AgentSpec, merge_db_overrides
from backend.orchestration.unified_schemas import (
    EntryField,
    EntryFieldType,
    build_entry_values_model,
)
from backend.prompts import unified as prompts

logger = get_logger("agent_registry")

_AGENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_RESERVED_LABELS = frozenset({"clarify", "multi_agent"})
_VALID_EXEC_MODES = frozenset({"stream", "task", "clarify", "pipeline"})
_VALID_ENTRY_TYPES = frozenset({t.value for t in EntryFieldType})


@dataclass
class AgentMeta:
    """一个 Agent 的注册元数据。

    前半部分为代码注册项（build_graph 无法入库），后半部分为 `agent` 表加载项。
    """

    agent_type: str
    build_graph: Callable[..., object]  # 返回编译后的 LangGraph (CompiledGraph)
    input_schema: Optional[dict] = None  # JSON Schema，供校验与文档
    enabled: bool = True  # 代码侧默认开关（库加载后以库为准）
    # —— 以下由 agent 表加载（未登记为 None）——
    name: Optional[str] = None
    description: Optional[str] = None
    db_enabled: Optional[bool] = None  # 库中全局开关；None 表示库未登记
    version: Optional[str] = None
    spec: Optional[AgentSpec] = None  # 统一入口规格


class AgentRegistry:
    """运行时 Agent 注册表：按 agent_type 找图，支持能力开关与按租户过滤。"""

    def __init__(self) -> None:
        self._agents: Dict[str, AgentMeta] = {}
        # 租户级能力策略缓存：(tenant_id, agent_type) -> enabled
        self._tenant_policy: Dict[tuple, bool] = {}
        # 派生物缓存（_rebuild_derived 重建）
        self._label_to_agent: Dict[str, str] = {}
        self._scope_by_agent: Dict[str, str] = {}
        self._entry_models: Dict[str, type] = {}
        self._specs_snapshot: List[AgentSpec] = []
        # 库规格是否成功加载；False 表示 load_from_db 失败、降级为仅代码注册值（R15/Q6）
        self._db_loaded: bool = False

    async def start(self) -> None:
        """启动：从库加载 Agent 元数据与租户策略（失败仅告警，不阻断启动）。"""
        await self.load_from_db()
        self.validate_specs()  # 启动期 fail-fast（V1–V14 可达项）

    async def load_from_db(self) -> None:
        """加载 `agent` 元数据 + `agent_capability_policy` 全量策略到内存。"""
        try:
            rows = await AgentDao.list_agents()
            loaded = 0
            for r in rows:
                meta = self._agents.get(r["agent_type"])
                if meta is None:
                    # 库里登记但代码未注册图：无法执行，仅告警（get() 会报未知类型）
                    logger.warning(f"Agent 已在库登记但未注册图构造器: {r['agent_type']}")
                    continue
                meta.name = r["name"]
                meta.description = r["description"]
                if r["input_schema"]:
                    meta.input_schema = r["input_schema"]
                meta.db_enabled = r["enabled"]
                meta.version = r["version"]
                if meta.spec is not None:
                    meta.spec = merge_db_overrides(
                        meta.spec,
                        name=r["name"],
                        description=r["description"],
                        version=r["version"],
                    )
                loaded += 1
            policies = await AgentDao.list_policies()
            self._tenant_policy = {
                (p["tenant_id"], p["agent_type"]): p["enabled"] for p in policies
            }
            logger.info(
                f"已从库加载 Agent 元数据 {loaded}/{len(rows)} 条、租户策略 {len(policies)} 条"
            )
            self._db_loaded = True
        except Exception as e:  # 库不可用/未建表时降级为「只用代码注册值」
            logger.exception(f"从库加载 Agent 元数据失败，使用代码注册默认值: {e}")
            self._db_loaded = False
        finally:
            self._rebuild_derived()

    async def refresh(self) -> None:
        """运行期重新加载（如库里改了开关/策略后调用）。"""
        await self.load_from_db()

    def register(
        self,
        agent_type: str,
        build_graph: Callable[..., object],
        input_schema: Optional[dict] = None,
        spec: Optional[AgentSpec] = None,
    ) -> None:
        """注册一个 Agent 图构造器；重复注册覆盖并告警。"""
        if agent_type in self._agents:
            logger.warning(f"Agent 重复注册，覆盖: {agent_type}")
        self._agents[agent_type] = AgentMeta(
            agent_type, build_graph, input_schema, spec=spec
        )
        logger.info(f"Agent 已注册: {agent_type}")

    def get(self, agent_type: str) -> AgentMeta:
        if agent_type not in self._agents:
            raise KeyError(f"未知 Agent 类型: {agent_type}")
        return self._agents[agent_type]

    def set_enabled(self, agent_type: str, enabled: bool) -> None:
        """全局能力开关（内存态；持久值在 agent.enabled，租户维度见策略表）。"""
        meta = self.get(agent_type)
        meta.enabled = enabled

    def is_enabled_for_tenant(self, agent_type: str, tenant_id: Optional[int] = None) -> bool:
        """该租户是否可用此 Agent = 全局开关 AND 租户策略。

        全局开关优先取库值（agent.enabled），库未登记时回退代码注册的 enabled；
        租户策略未配置视为开通（不限制未配置的租户）。
        """
        meta = self._agents.get(agent_type)
        if meta is None:
            return False
        global_on = meta.db_enabled if meta.db_enabled is not None else meta.enabled
        if not global_on:
            return False
        if tenant_id is None:
            return True
        return self._tenant_policy.get((tenant_id, agent_type), True)

    def list_types(self, only_enabled: bool = True, tenant_id: Optional[int] = None) -> List[str]:
        """列出 Agent 类型；传 tenant_id 时按租户开通策略过滤。"""
        if tenant_id is not None:
            return [
                t
                for t in self._agents
                if (self.is_enabled_for_tenant(t, tenant_id) or not only_enabled)
            ]
        return [t for t, m in self._agents.items() if (m.enabled or not only_enabled)]

    def specs(self, *, tenant_id: Optional[int] = None) -> List[AgentSpec]:
        """供统一编排层无锁读取；tenant_id 给定时按 is_enabled_for_tenant 过滤。"""
        return [
            m.spec
            for m in self._agents.values()
            if m.spec is not None
            and self.is_enabled_for_tenant(m.agent_type, tenant_id)
        ]

    def is_registered(self, agent_type: str) -> bool:
        """agent_type 是否在注册表中有定义（忽略启用态）。

        用于区分「完全未知的类型」与「已注册但被停用」，前者走兜底、后者应被明确拒绝。
        """
        return agent_type in self._agents

    @property
    def db_loaded(self) -> bool:
        """库规格是否成功加载；False 表示降级为仅代码注册 Agent 可用（R15/Q6）。"""
        return self._db_loaded

    def spec_for(self, agent_type: str) -> Optional[AgentSpec]:
        """按 agent_type 取当前启用的 spec；未注册或已停用返回 None。

        公开包装，供 HTTP 层（unified_chat）等无需关心启用过滤细节的调用方使用；
        语义与 `specs()` 一致（按全局 enabled 过滤）。
        """
        meta = self._agents.get(agent_type)
        if meta is None or meta.spec is None:
            return None
        if not self.is_enabled_for_tenant(agent_type, None):
            return None
        return meta.spec

    def get_entry_model(self, agent_type: str):
        """取动态生成的入口校验模型（Step 2 build_entry_values_model 产物）。"""
        return self._entry_models.get(agent_type)

    def label_to_agent(self, label: str) -> Optional[str]:
        return self._label_to_agent.get(label)

    def scope_for_agent(self, agent_type: str) -> Optional[str]:
        return self._scope_by_agent.get(agent_type)

    def render_route_prompt(self) -> str:
        """渲染意图分类 system 提示词（仅含启用 spec）。"""
        lines = []
        for spec in self.specs():
            lines.append(f"- {spec.agent_type}（{spec.display_name}）：{spec.description}")
            if spec.intent_hint:
                lines.append(f"  提示：{spec.intent_hint}")
            for ex in spec.intent_examples:
                lines.append(f"  示例：{ex}")
        return prompts.ROUTE_SYSTEM_PROMPT.format(agent_list="\n".join(lines))

    def render_turn_input(self, history: str, user_input: str) -> str:
        return prompts.ROUTE_TURN_TEMPLATE.format(history=history, user_input=user_input)

    def _rebuild_derived(self) -> None:
        """每次 load_from_db 末尾原子重建派生物；编排层只读。"""
        label_map: Dict[str, str] = {}
        scope_map: Dict[str, str] = {}
        entry_models: Dict[str, type] = {}
        for meta in self._agents.values():
            spec = meta.spec
            if spec is None:
                continue
            for label in spec.intent_labels:
                if label in _RESERVED_LABELS:
                    continue
                label_map[label] = spec.agent_type
            if spec.scope:
                scope_map[spec.agent_type] = spec.scope
            if spec.entry_fields:
                entry_models[spec.agent_type] = build_entry_values_model(
                    list(spec.entry_fields), spec.agent_type
                )
        self._label_to_agent = label_map
        self._scope_by_agent = scope_map
        self._entry_models = entry_models
        self._specs_snapshot = [
            m.spec for m in self._agents.values() if m.spec is not None
        ]

    def validate_specs(self) -> None:
        """启动期 fail-fast 校验（§3.5 V1–V14 可达项）。

        依赖 Step 7/10 的白名单与预算项（V6/V7/V10/V11）本步仅告警，待接回 fail-fast。
        """
        from backend.security.rbac import VALID_SCOPES

        specs = [m.spec for m in self._agents.values() if m.spec is not None]

        # V1 agent_type 唯一/格式
        seen: set[str] = set()
        for s in specs:
            if not s.agent_type or not _AGENT_TYPE_RE.match(s.agent_type):
                raise ValueError(f"[V1] 非法 agent_type: {s.agent_type!r}")
            if s.agent_type in seen:
                raise ValueError(f"[V1] 重复 agent_type: {s.agent_type}")
            seen.add(s.agent_type)

        # V2 恰有一个 default_agent
        defaults = [s for s in specs if s.default_agent]
        if len(defaults) != 1:
            raise ValueError(f"[V2] default_agent 必须恰有 1 个，实际 {len(defaults)}")

        # V3 intent_labels 全局唯一且不占内建 label
        label_map: Dict[str, str] = {}
        for s in specs:
            for label in s.intent_labels:
                if label in _RESERVED_LABELS:
                    raise ValueError(f"[V3] 占用了内建 label: {label}")
                if label in label_map:
                    raise ValueError(
                        f"[V3] intent_labels 重复: {label}（{label_map[label]} / {s.agent_type}）"
                    )
                label_map[label] = s.agent_type

        # V4 scope/menu_scope 在合法集合内
        for s in specs:
            if s.scope and s.scope not in VALID_SCOPES:
                raise ValueError(f"[V4] scope 不在 VALID_SCOPES: {s.scope}")
            if s.menu_scope and s.menu_scope not in VALID_SCOPES:
                raise ValueError(f"[V4] menu_scope 不在 VALID_SCOPES: {s.menu_scope}")

        # V5 execution_mode 合法
        for s in specs:
            if s.execution_mode not in _VALID_EXEC_MODES:
                raise ValueError(f"[V5] 非法 execution_mode: {s.execution_mode}")

        # V8 每个注册 Agent 都有非空 spec
        for at, meta in self._agents.items():
            if meta.spec is None:
                raise ValueError(f"[V8] Agent {at} 未提供 spec")

        # V13 动态入口校验模型可构造并对样例校验；entry 字段类型受约束
        for s in specs:
            for ef in s.entry_fields:
                if ef.type.value not in _VALID_ENTRY_TYPES:
                    raise ValueError(f"[V13] {s.agent_type} 入口字段类型非法: {ef.type}")
            if s.entry_fields:
                model = build_entry_values_model(list(s.entry_fields), s.agent_type)
                sample = {ef.name: _sample_value(ef) for ef in s.entry_fields}
                try:
                    model(**sample)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(f"[V13] {s.agent_type} 动态模型样例校验失败: {exc}")

        # V14 提示词常量齐全非空，且路由提示词可渲染
        required_prompts = [
            "ROUTE_SYSTEM_PROMPT", "ROUTE_TURN_TEMPLATE", "RULE_REPLY_GREETING",
            "RULE_REPLY_THANKS", "RULE_REPLY_BYE", "RULE_REPLY_IDENTITY",
            "RULE_REPLY_CAPABILITY", "DYNAMIC_CAPABILITY_ITEM", "CLARIFY_TEMPLATE",
            "SUMMARY_COMPRESS_PROMPT", "LONG_MEMORY_EXTRACT_PROMPT",
            "PIPELINE_PLAN_PROMPT", "TASK_GUIDANCE_TEMPLATE",
        ]
        for name in required_prompts:
            if not getattr(prompts, name):
                raise ValueError(f"[V14] 提示词常量空串: {name}")
        try:
            self.render_route_prompt()
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"[V14] render_route_prompt 失败: {exc}")

        # V6 / V7 / V10 / V11 / V12：依赖 Step 7/10 的白名单与预算，本步仅告警
        for s in specs:
            if s.route_key:
                logger.warning(
                    f"[V6-soft] {s.agent_type}.route_key={s.route_key}（ROUTE_KEYS 白名单校验延后至 Step 7）"
                )
            if s.menu and s.menu.icon:
                logger.warning(
                    f"[V7-soft] {s.agent_type} menu.icon={s.menu.icon}（ICONS 白名单校验延后至 Step 10）"
                )
            if s.tags and any(len(t) > 64 for t in s.tags):
                logger.warning(f"[V10-soft] {s.agent_type} 存在超长 tag（Langfuse 约束）")
            if s.execution_mode == "task" and not (s.accept_files or s.entry_fields):
                logger.warning(
                    f"[V12-soft] {s.agent_type} task 模式缺少 accept_files/entry_fields"
                )
            if s.execution_mode == "stream" and not s.generate_nodes:
                logger.warning(
                    f"[V6-soft] {s.agent_type} stream 模式未声明 generate_nodes"
                )
        est = len(self.render_route_prompt())
        if est > 8000:
            logger.warning(f"[V11-soft] 路由提示词约 {est} 字符，超出 token 预算")

    async def stop(self) -> None:
        self._agents.clear()
        self._tenant_policy.clear()


def _sample_value(ef: EntryField) -> object:
    """为 V13 样例校验生成入口字段样例值。"""
    if ef.type == EntryFieldType.ENUM and ef.options:
        return ef.options[0]
    if ef.default is not None:
        return ef.default
    return {
        EntryFieldType.STR: "x",
        EntryFieldType.INT: 0,
        EntryFieldType.FLOAT: 0.0,
        EntryFieldType.BOOL: False,
        EntryFieldType.UUID: "00000000-0000-0000-0000-000000000000",
        EntryFieldType.ENUM: "x",
    }[ef.type]
