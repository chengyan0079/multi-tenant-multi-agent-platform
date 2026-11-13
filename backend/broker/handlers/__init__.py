"""handler 注册表：TaskType → 处理函数，三处（枚举/队列/注册）须一致，handler 内先做鉴权。"""

from backend.broker.handlers.audit import handle_audit_flush
from backend.broker.handlers.qa_parse import handle_qa_parse
from backend.broker.handlers.qa_ragas import handle_qa_ragas_review
from backend.broker.handlers.notify import handle_notify_send
from backend.broker.handlers.exam import handle_exam_review
from backend.broker.handlers.resume import handle_resume_review
from backend.broker.types import TaskType

HANDLERS: dict[TaskType, object] = {
    TaskType.AUDIT_FLUSH: handle_audit_flush,
    TaskType.NOTIFY_SEND: handle_notify_send,
    TaskType.QA_PARSE: handle_qa_parse,
    TaskType.QA_RAGAS_REVIEW: handle_qa_ragas_review,
    TaskType.RESUME_REVIEW: handle_resume_review,
    TaskType.EXAM_REVIEW: handle_exam_review,
}
