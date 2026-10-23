"""api/v1 包：聚合全部路由。"""
from backend.api.v1 import config_center, escalations, orchestrator, plugins, threads, unified_chat
from backend.agents.exam.api import router as exam_router
from backend.agents.interview.api import router as interview_router
from backend.agents.qa.api import router as qa_router
from backend.agents.resume.api import router as resume_router

__all__ = [
    "unified_chat",
    "orchestrator",
    "threads",
    "plugins",
    "escalations",
    "config_center",
    "resume_router",
    "qa_router",
    "exam_router",
    "interview_router",
]
