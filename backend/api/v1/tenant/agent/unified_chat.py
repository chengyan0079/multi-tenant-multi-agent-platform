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
from pydantic import BaseModel
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

_USAGE_INPUT_KEYS = (
    "sql_text",
    "db_type",
    "target_database",
    "connection_id",
    "request_id",
    "sandbox_connection_id",
)


def _estimate_usage(prompt_text: str, completion_text: str) -> dict:
    """按字符估算 token（中文约 2 字符/token）；标注 estimated 供前端显示 ≈。"""
    from math import ceil

    p = len(prompt_text or "")
    c = len(completion_text or "")
    return {
        "prompt": ceil(p / 2),
        "completion": ceil(c / 2),
        "total": ceil((p + c) / 2),
        "estimated": True,
    }


def _usage_or_estimate(usage: dict | None, initial: dict, state: dict) -> dict:
    """真实 usage 优先；网关不返回 usage 时按入口输入 + 结果内容估算。"""
    if int((usage or {}).get("total") or 0) > 0:
        return dict(usage or {})
    prompt_text = json.dumps(
        {k: (initial or {}).get(k) for k in _USAGE_INPUT_KEYS},
        ensure_ascii=False,
        default=str,
    )
    completion_text = str((state or {}).get("answer") or "") + str(
        (state or {}).get("final_sql") or ""
    )
    return _estimate_usage(prompt_text, completion_text)

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
            # 入口分流：并行且无 HITL 的组合（qa 规范 + db_review 评审）直接编排；
            # 串行含审批（interrupt）不放这里，走「变更编排」页逐阶段推进。
            from backend.common.logger import get_logger
            from backend.services.intent_router import classify_intent

            _log = get_logger("unified_chat")
            try:
                decision = await classify_intent(req.message, tenant_id)
            except Exception as exc:  # noqa: BLE001 - 意图失败降级为原路由
                _log.warning(f"intent 分流失败，降级原路由: {exc}")
                decision = {}
            entry_inputs = {
                f.name: f.value for f in (req.entry.fields if req.entry else [])
            }
            if (
                decision.get("flow") == "parallel"
                and entry_inputs.get("sql_text")
                and entry_inputs.get("connection_id")
            ):
                from langchain_core.messages import HumanMessage

                yield {
                    "data": json.dumps(
                        {
                            "type": "routing_decision",
                            "agent_type": "multi_agent",
                            "intent": decision.get("intent"),
                            "flow": "parallel",
                            "agents": decision.get("agents"),
                            "confidence": decision.get("confidence"),
                        },
                        ensure_ascii=False,
                    )
                }
                inputs = {
                    **entry_inputs,
                    "messages": [HumanMessage(content=req.message)],
                    "query": req.message,
                    "tenant_id": tenant_id,
                    "user_id": current.user_id,
                    "session_id": req.session_id,
                }
                orch = app_state.orchestrator
                if orch is not None:
                    res = await orch.run_parallel(
                        decision.get("agents") or [], req.session_id, inputs
                    )
                    yield {
                        "data": json.dumps(
                            {
                                "type": "orchestration_result",
                                "flow": "parallel",
                                "agents": decision.get("agents"),
                                "result": res,
                            },
                            ensure_ascii=False,
                            default=str,
                        )
                    }
                    yield {"data": json.dumps({"type": "done"}, ensure_ascii=False)}
                    return

            # 业务型 Agent（db_review / db_release）：真流式；interrupt 时推审批事件，
            # 前端弹框 → 调 /unified/chat/resume 继续流式（无需刷新）
            _agent = (
                (req.agent_type or (decision.get("agents") or [None])[0])
                if decision
                else req.agent_type
            )
            if _agent in ("db_review", "db_release") and entry_inputs:
                import uuid as _uuid

                thread_key = f"t{tenant_id}:u{current.user_id}:{_uuid.uuid4().hex}"
                initial = {
                    **entry_inputs,
                    "tenant_id": tenant_id,
                    "user_id": current.user_id,
                    "session_id": thread_key,
                    "turn_id": _uuid.uuid4().hex,
                    "trace_id": _uuid.uuid4().hex,
                }
                orch = app_state.orchestrator
                if orch is not None:
                    import time as _time

                    _t0 = _time.perf_counter()
                    _usage: dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}
                    yield {
                        "data": json.dumps(
                            {
                                "type": "routing_decision",
                                "agent_type": _agent,
                                "thread_id": thread_key,
                            },
                            ensure_ascii=False,
                        )
                    }
                    try:
                        from backend.orchestration.unified_dispatch import _extract_usage

                        async for ev in orch.run_agent_stream(_agent, thread_key, initial):
                            if ev.get("event") == "on_chat_model_stream":
                                chunk = (ev.get("data") or {}).get("chunk")
                                content = getattr(chunk, "content", "") or ""
                                if content:
                                    yield {
                                        "data": json.dumps(
                                            {"type": "token", "content": content},
                                            ensure_ascii=False,
                                        )
                                    }
                            elif ev.get("event") == "on_chat_model_end":
                                usage = _extract_usage((ev.get("data") or {}).get("output"))
                                for _k in ("prompt", "completion", "total"):
                                    if usage.get(_k):
                                        _usage[_k] = _usage.get(_k, 0) + int(usage[_k])
                    except Exception as exc:  # noqa: BLE001
                        _log.warning(f"{_agent} 流式失败: {exc}")
                        yield {
                            "data": json.dumps(
                                {"type": "error", "code": "UPSTREAM", "message": str(exc)},
                                ensure_ascii=False,
                            )
                        }
                    # 流结束后判断是否 interrupt（HITL）：前端弹框，不刷新
                    try:
                        state = await orch.get_state(_agent, thread_key)
                    except Exception:  # noqa: BLE001
                        state = {}
                    if "__interrupt__" in state:
                        # 审批前不展示，但把统计（真实或估算）写入状态，供审批后汇总
                        try:
                            await orch.update_state(
                                _agent,
                                thread_key,
                                {
                                    "gate_token_usage": _usage_or_estimate(
                                        _usage, initial, state
                                    ),
                                    "gate_latency_ms": int(
                                        (_time.perf_counter() - _t0) * 1000
                                    ),
                                },
                            )
                        except Exception:  # noqa: BLE001 - SQL 异常必须暴露，不降级
                            raise
                        gate = (
                            "change_approve"
                            if _agent == "db_review"
                            else "gate_approve"
                        )
                        yield {
                            "data": json.dumps(
                                {
                                    "type": "interrupt",
                                    "agent_type": _agent,
                                    "thread_id": thread_key,
                                    "gate": gate,
                                    "request_id": state.get("request_id"),
                                    "risk_level": state.get("risk_level"),
                                    "answer": state.get("answer"),
                                },
                                ensure_ascii=False,
                                default=str,
                            )
                        }
                    else:
                        yield {
                            "data": json.dumps(
                                {
                                    "type": "result_card",
                                    "agent_type": _agent,
                                    "thread_id": thread_key,
                                    "request_id": state.get("request_id"),
                                    "risk_level": state.get("risk_level"),
                                    "status": state.get("release_status") or "done",
                                    "final_sql": state.get("final_sql"),
                                    "answer": state.get("answer"),
                                    "suggestions": state.get("suggestions") or [],
                                    "latency_ms": int((_time.perf_counter() - _t0) * 1000),
                                    "token_usage": _usage_or_estimate(
                                        _usage, initial, state
                                    ),
                                },
                                ensure_ascii=False,
                                default=str,
                            )
                        }
                    yield {"data": json.dumps({"type": "done"}, ensure_ascii=False)}
                    return

            async for ev in graph.run_stream(
                session_id=req.session_id,
                tenant_id=tenant_id,
                user_id=current.user_id,
                message=req.message,
                agent_type=req.agent_type,
                entry=req.entry,
                attachments=req.attachments or [],
                thinking=req.thinking,
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
            from backend.common.logger import get_logger as _get_logger

            _get_logger("unified_chat").exception(
                f"统一咨询执行失败: {type(exc).__name__}: {exc}"
            )
            # 异常不吞：把业务码与原始信息透给前端展示（DB 写入失败等）
            code = getattr(exc, "code", None) or "INTERNAL"
            msg = getattr(exc, "msg", None) or str(exc) or type(exc).__name__
            yield {
                "data": json.dumps(
                    {"type": "error", "code": str(code), "message": msg},
                    ensure_ascii=False,
                )
            }
        finally:
            _STOP_FLAGS.pop(req.session_id, None)

    return EventSourceResponse(event_gen(), ping=15)


class ResumeChatRequest(BaseModel):
    thread_id: str
    agent_type: str
    approved: bool = True
    comment: str | None = None
    turn_id: str | None = None  # pipeline 断点续跑用；不传则从 thread_id 末段解析
    session_id: str | None = None


@router.post("/chat/resume")
async def unified_chat_resume(
    req: ResumeChatRequest,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
    request: Request = None,
):
    """审批后继续真流式输出（Command(resume) + astream_events），无需刷新页面。"""
    app_state = request.app.state.app_state

    async def event_gen():
        orch = app_state.orchestrator
        if orch is None:
            yield {"data": json.dumps({"type": "error", "message": "编排器未就绪"})}
            return
        import time as _time

        _t0 = _time.perf_counter()
        _usage: dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}
        try:
            from backend.orchestration.unified_dispatch import _extract_usage

            async for ev in orch.astream_resume(
                req.agent_type,
                req.thread_id,
                {"approved": req.approved, "comment": req.comment},
            ):
                if ev.get("event") == "on_chat_model_stream":
                    chunk = (ev.get("data") or {}).get("chunk")
                    content = getattr(chunk, "content", "") or ""
                    if content:
                        yield {
                            "data": json.dumps(
                                {"type": "token", "content": content}, ensure_ascii=False
                            )
                        }
                elif ev.get("event") == "on_chat_model_end":
                    usage = _extract_usage((ev.get("data") or {}).get("output"))
                    for _k in ("prompt", "completion", "total"):
                        if usage.get(_k):
                            _usage[_k] = _usage.get(_k, 0) + int(usage[_k])
        except Exception as exc:  # noqa: BLE001
            yield {
                "data": json.dumps(
                    {"type": "error", "code": "UPSTREAM", "message": str(exc)},
                    ensure_ascii=False,
                )
            }
        try:
            state = await orch.get_state(req.agent_type, req.thread_id)
        except Exception:  # noqa: BLE001
            state = {}

        # 最终统计 = 审批前段（state）+ 审批后段（本次）；两段都无真实 usage 时整体估算
        gate_usage = state.get("gate_token_usage") or {}
        final_usage = {
            k: int(gate_usage.get(k, 0)) + int(_usage.get(k, 0))
            for k in ("prompt", "completion", "total")
        }
        if final_usage["total"] <= 0:
            final_usage = _estimate_usage(
                json.dumps(
                    {
                        k: state.get(k)
                        for k in ("request_id", "sandbox_connection_id", "sql_text")
                    },
                    ensure_ascii=False,
                    default=str,
                )
                + str(req.comment or ""),
                str(state.get("answer") or "") + str(state.get("final_sql") or ""),
            )
        elif gate_usage.get("estimated") or _usage.get("estimated"):
            final_usage["estimated"] = True

        yield {
            "data": json.dumps(
                {
                    "type": "result_card",
                    "agent_type": req.agent_type,
                    "thread_id": req.thread_id,
                    "request_id": state.get("request_id"),
                    "risk_level": state.get("risk_level"),
                    "status": state.get("release_status")
                    or ("approved" if req.approved else "rejected"),
                    "final_sql": state.get("final_sql"),
                    "answer": state.get("answer"),
                    "suggestions": state.get("suggestions") or [],
                    # 最终统一展示：审批前段（state 里）+ 审批后段（本次）累计
                    "latency_ms": int((_time.perf_counter() - _t0) * 1000)
                    + int(state.get("gate_latency_ms") or 0),
                    "token_usage": final_usage,
                },
                ensure_ascii=False,
                default=str,
            )
        }
        # pipeline 断点续跑：本轮是串行中的一步时，按 turn 表里的 plan 决定终止或继续
        try:
            turn_id = req.turn_id or req.thread_id.rsplit(":", 1)[-1]
            from backend.data.dao.agent.unified_turn_dao import UnifiedTurnDao

            row = await UnifiedTurnDao.get_by_id(
                turn_id, tenant_id=int(current.tenant_id), user_id=int(current.user_id)
            )
            routing = (row or {}).get("routing") or {}
            if isinstance(routing, str):
                import json as _json

                routing = _json.loads(routing)
            plan = routing.get("plan") if isinstance(routing, dict) else None
            if plan and plan.get("steps"):
                if not req.approved:
                    yield {
                        "data": json.dumps(
                            {
                                "type": "pipeline_result",
                                "content": "",
                                "status": "rejected",
                                "stopped_at": req.agent_type,
                            },
                            ensure_ascii=False,
                        )
                    }
                else:
                    current_step = int((state.get("_pipeline_current_step") or 0))
                    remaining = list(plan["steps"])[current_step:]
                    if remaining:
                        rest_plan = {"type": "sequence", "steps": remaining}
                        carry = {
                            "query": str(state.get("answer") or state.get("query") or ""),
                            "messages": [],
                            "tenant_id": int(current.tenant_id),
                            "user_id": int(current.user_id),
                            "session_id": req.session_id or "",
                            "thread_id": (row or {}).get("thread_id") or req.thread_id,
                            "turn_id": turn_id,
                            "trace_id": (row or {}).get("trace_id") or "",
                        }
                        rest = await orch.run_plan(rest_plan, carry["thread_id"], carry)
                        for item in rest.get("_step_results") or []:
                            yield {
                                "data": json.dumps(
                                    {
                                        "type": "pipeline_step_result",
                                        "step": item.get("step"),
                                        "agent_type": item.get("agent_type"),
                                        "content": item.get("content"),
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        yield {
                            "data": json.dumps(
                                {
                                    "type": "pipeline_result",
                                    "content": str(rest.get("content") or ""),
                                    "status": "done",
                                },
                                ensure_ascii=False,
                            )
                        }
        except Exception as exc:  # noqa: BLE001 - 续跑失败只告警，主 result_card 已发出
            from backend.common.logger import get_logger as _get_logger

            _get_logger("unified_chat").warning(f"pipeline resume 续跑失败: {exc}")

        yield {"data": json.dumps({"type": "done"}, ensure_ascii=False)}

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


@router.get("/tools")
async def unified_tools(
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
    request: Request = None,
) -> Any:
    """当前租户工具列表（含启停状态），供聊天框内快捷启停。"""
    from backend.data.dao.agent.tool_dao import ToolDao

    rows, _total = await ToolDao.list_paged(
        tenant_id=current.tenant_id, page=1, page_size=200
    )
    return success(
        [
            {
                "id": r["id"],
                "name": r["name"],
                "description": r.get("description") or "",
                "enabled": bool(r.get("enabled")),
            }
            for r in rows
        ]
    )


class ToolEnabledIn(BaseModel):
    enabled: bool


@router.patch("/tools/{tool_id}/enabled")
async def unified_tool_enabled(
    tool_id: str,
    body: ToolEnabledIn,
    current: CurrentUser = Depends(get_current_user),
    _: object = Depends(require_scope(Scope.UNIFIED_ASK)),
    request: Request = None,
) -> Any:
    """聊天框内快捷启停工具（按租户校验归属后生效，并刷新插件注册表）。"""
    from backend.data.dao.agent.tool_dao import ToolDao

    row = await ToolDao.get(tool_id)
    if row is None or int(row.get("tenant_id") or 0) != int(current.tenant_id):
        return success({"ok": False, "error": "工具不存在或不属于当前租户"})
    await ToolDao.set_enabled(tool_id, body.enabled)
    try:
        from backend.server.managers.plugin_manager import reload_plugins

        await reload_plugins()
    except Exception:  # noqa: BLE001 - 刷新失败不影响本次状态更新
        pass
    return success({"ok": True, "id": tool_id, "enabled": body.enabled})


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
