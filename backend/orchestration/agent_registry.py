"""Agent 注册/发现：启动注册 build_graph，元数据与开通策略入内存，运行期可 refresh。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from backend.common.logger import get_logger
from backend.data.dao.agent.agent_dao import AgentDao

logger = get_logger("agent_registry")


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


class AgentRegistry:
    """运行时 Agent 注册表：按 agent_type 找图，支持能力开关与按租户过滤。"""

    def __init__(self) -> None:
        self._agents: Dict[str, AgentMeta] = {}
        # 租户级能力策略缓存：(tenant_id, agent_type) -> enabled
        self._tenant_policy: Dict[tuple, bool] = {}

    async def start(self) -> None:
        """启动：从库加载 Agent 元数据与租户策略（失败仅告警，不阻断启动）。"""
        await self.load_from_db()

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
                loaded += 1
            policies = await AgentDao.list_policies()
            self._tenant_policy = {
                (p["tenant_id"], p["agent_type"]): p["enabled"] for p in policies
            }
            logger.info(
                f"已从库加载 Agent 元数据 {loaded}/{len(rows)} 条、租户策略 {len(policies)} 条"
            )
        except Exception as e:  # 库不可用/未建表时降级为「只用代码注册值」
            logger.exception(f"从库加载 Agent 元数据失败，使用代码注册默认值: {e}")

    async def refresh(self) -> None:
        """运行期重新加载（如库里改了开关/策略后调用）。"""
        await self.load_from_db()

    def register(
        self,
        agent_type: str,
        build_graph: Callable[..., object],
        input_schema: Optional[dict] = None,
    ) -> None:
        """注册一个 Agent 图构造器；重复注册覆盖并告警。"""
        if agent_type in self._agents:
            logger.warning(f"Agent 重复注册，覆盖: {agent_type}")
        self._agents[agent_type] = AgentMeta(agent_type, build_graph, input_schema)
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

    async def stop(self) -> None:
        self._agents.clear()
        self._tenant_policy.clear()
