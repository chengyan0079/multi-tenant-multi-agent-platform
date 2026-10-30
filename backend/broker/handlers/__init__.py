"""handler 注册表：消息 type → 处理函数。

新增业务类型时，在此注册并补充对应 handler 模块；consumer 按 type 路由。
每个 handler 内部应先调用 authorize_task 做租户 / scope 鉴权（见 broker/security.py）。
"""
from backend.broker.handlers.agent import handle_agent_run
from backend.broker.handlers.audit import handle_audit_flush
from backend.broker.handlers.knowledge import handle_knowledge_reindex
from backend.broker.handlers.notify import handle_notify_send

HANDLERS: dict[str, object] = {
    "audit.flush": handle_audit_flush,
    "notify.send": handle_notify_send,
    "agent.run": handle_agent_run,
    "knowledge.reindex": handle_knowledge_reindex,
}
