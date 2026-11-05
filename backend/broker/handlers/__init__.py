"""handler 注册表：消息类型 → 处理函数。

新增业务类型时，在 TaskType 加枚举、在 topology.TASK_QUEUES 加队列、在此注册 handler，
三处必须一致（启动期由 topology.validate_handler_coverage 校验）。
每个 handler 内部应先调用 authorize_task 做租户 / scope 鉴权（见 broker/security.py）。
"""
from backend.broker.handlers.agent import handle_agent_run
from backend.broker.handlers.audit import handle_audit_flush
from backend.broker.handlers.config_refresh import handle_config_refresh
from backend.broker.handlers.doc_parse import handle_doc_parse
from backend.broker.handlers.knowledge import handle_knowledge_reindex
from backend.broker.handlers.notify import handle_notify_send
from backend.broker.handlers.resume import handle_resume_review
from backend.broker.types import TaskType

HANDLERS: dict[TaskType, object] = {
    TaskType.AUDIT_FLUSH: handle_audit_flush,
    TaskType.NOTIFY_SEND: handle_notify_send,
    TaskType.AGENT_RUN: handle_agent_run,
    TaskType.KNOWLEDGE_REINDEX: handle_knowledge_reindex,
    TaskType.DOC_PARSE: handle_doc_parse,
    TaskType.RESUME_REVIEW: handle_resume_review,
    TaskType.CONFIG_REFRESH: handle_config_refresh,
}
