"""统一咨询入口：对话 / 附件 / 能力卡片（§8.1，scope unified:ask）。

- POST /unified/chat/stream：SSE 真流式（逐 token/进度），首帧 routing_decision，尾帧 done。
- POST /unified/chat/stop：best-effort 停止（单进程内存标记，多进程需共享存储）。
- POST /unified/attachments：两阶段上传第一步，返回 file_ref。
- GET  /unified/agents：能力卡片（前端空态 + 模板问题）。
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sse_starlette.sse import EventSourceResponse

from backend.api.v1.tenant.agent import unified_deps
from backend.api.v1.tenant.agent.unified_dtos import (
    AgentCapabilityView,
    StopChatRequest,
    UnifiedChatRequest,
)
from backend.common.response import success
from backend.middleware.auth import CurrentUser, get_current_user, tenant_of
from backend.security.rbac import Scope
from backend.security.security import require_scope
from backend.services.attachment_service import AttachmentError, upload_attachment

router = APIRouter(prefix="/unified", tags=["unified"])

# best-effort 停止标记：单进程内存态；多副本部署需换成 redis/共享存储
_STOP_FLAGS: dict[str, bool] = {}


@router.post("/chat/stream")
async def unified_chat_stream(
    req: UnifiedChatRequest,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
    request: Request = None,
):
    tenant_id = tenant_of(current)
    app_state = request.app.state.app_state
    graph = unified_deps.build_unified_graph(app_state)
    spec = app_state.agent_registry.spec_for(req.agent_type) if req.agent_type else None
    accept_exts = spec.accept_files if spec else None

    async def event_gen():
        _STOP_FLAGS.pop(req.session_id, None)
        try:
            async for ev in graph.run_stream(
                session_id=req.session_id,
                tenant_id=tenant_id,
                user_id=current.user_id,
                message=req.message,
                agent_type=req.agent_type,
                entry=req.entry,
                attachments=req.attachments or [],
            ):
                if _STOP_FLAGS.get(req.session_id):
                    # 显式告知前端已停止，避免只能等 2s abort 兜底
                    yield {"data": json.dumps({"type": "stopped"}, ensure_ascii=False)}
                    break
                yield {
                    "data": json.dumps(
                        {"type": ev.event_type, **ev.payload.model_dump()},
                        ensure_ascii=False,
                    )
                }
        except Exception as exc:  # noqa: BLE001 - 上游异常转为 error 帧，前端可渲染
            yield {
                "data": json.dumps(
                    {"type": "error", "code": "UPSTREAM", "message": str(exc)},
                    ensure_ascii=False,
                )
            }
        finally:
            _STOP_FLAGS.pop(req.session_id, None)

    return EventSourceResponse(event_gen(), ping=15)


@router.post("/chat/stop")
async def unified_chat_stop(
    req: StopChatRequest,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
) -> Any:
    _STOP_FLAGS[req.session_id] = True
    return success({"ok": True})


@router.post("/attachments")
async def unified_upload_attachment(
    file: UploadFile = File(...),
    agent_type: str | None = Form(None),
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
    request: Request = None,
) -> Any:
    app_state = request.app.state.app_state
    spec = app_state.agent_registry.spec_for(agent_type) if agent_type else None
    accept_exts = spec.accept_files if spec else None
    try:
        ref = await upload_attachment(
            file=file,
            tenant_id=tenant_of(current),
            user_id=current.user_id,
            accept_exts=accept_exts,
        )
        return success(ref)
    except AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agents")
async def unified_list_agents(
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
    request: Request = None,
) -> Any:
    registry = request.app.state.app_state.agent_registry
    # specs(tenant_id=...) 已按 is_enabled_for_tenant 过滤（全局开关 AND 租户策略）
    cards = [
        AgentCapabilityView(
            agent_type=s.agent_type,
            display_name=s.display_name,
            description=s.description,
            card=s.card,
            templates=s.templates,
            entry_fields=s.entry_fields,
            accept_files=s.accept_files,
            route_key=s.route_key,
            tags=s.tags,
        )
        for s in registry.specs(tenant_id=tenant_of(current))
    ]
    return success(cards)
