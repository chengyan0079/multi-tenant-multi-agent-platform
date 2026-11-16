"""agents 包：Agent 构造器显式登记 + 由 DB 驱动注册。

注册唯一来源 = `agent` 表（`tenant_id` + `enabled`）。
本模块只提供代码能力池 ``AGENT_BUILDERS``，**不扫描目录/命名**；新增 Agent：
定义类并在 ``AGENT_BUILDERS`` 显式登记一行，DB 插入注册行后才生效。
"""

from __future__ import annotations

from typing import Dict, Type

from backend.agents.base import Agent
from backend.agents.db_release.agent import DbReleaseAgent
from backend.agents.db_review.agent import DbReviewAgent
from backend.agents.qa.agent import QAAgent

# agent_type -> Agent 类（代码能力池；不依赖路径/命名）
AGENT_BUILDERS: Dict[str, Type[Agent]] = {
    QAAgent.agent_type: QAAgent,
    DbReviewAgent.agent_type: DbReviewAgent,
    DbReleaseAgent.agent_type: DbReleaseAgent,
}


def iter_agent_classes() -> list[type[Agent]]:
    """返回显式登记的构造器类（兼容旧调用）。"""
    return list(AGENT_BUILDERS.values())
