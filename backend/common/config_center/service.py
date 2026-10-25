"""
service - 配置中心审批流服务（ConfigChangeService，对齐 RAG-Ultra）

职责：申请 / 复核 / 执行 / 回滚 / 列表查询。所有 Nacos 写操作仅在审批通过后由本服务触发，
并携带 casMd5 做乐观锁（见 RAG-Ultra docs/配置中心对接设计.md §6.1）。

并发控制（配置中心为管理员低频操作，无高并发）：
- 悲观锁：复核时对申请单行加 FOR UPDATE，保证状态只迁移一次。
- 乐观锁：执行 Nacos 写时携带申请时抓取的当前 md5 作为 casMd5；期间若配置被改则拒绝。

数据访问：`ConfigDao` 只负责 SQL，事务边界留在本模块（`session.commit()` / `rollback()`），
因为「复核 → 调 Nacos → 回填 nid」必须是一个可回滚的整体。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.config_center.groups import ConfigGroup
from backend.common.config_center.nacos_config import ConfigCenterError, get_config_center_client
from backend.common.config_center.prompts_cache import refresh_prompt
from backend.common.logger import logger
from backend.observability.exception import BizException
from backend.data.dao.ops.config_dao import ConfigDao
from backend.middleware.auth import user_id_ctx

# 操作类型
OP_ADD = 1
OP_MODIFY = 2
OP_DELETE = 3
OP_ROLLBACK = 4

# 申请状态
ST_PENDING = 0
ST_APPROVED = 1
ST_REJECTED = 2
ST_EXECUTED = 3

# 复核动作
RV_PASS = 1
RV_REJECT = 2

_OP_NAME = {OP_ADD: "新增", OP_MODIFY: "修改", OP_DELETE: "删除", OP_ROLLBACK: "回滚"}


def _operator() -> int | None:
    return user_id_ctx.get()


async def _nacos_call(fn, *args, **kwargs):
    """把同步 Nacos 客户端调用丢到线程池，避免阻塞事件循环。"""
    return await asyncio.to_thread(fn, *args, **kwargs)


def _infer_format(data_id: str) -> str | None:
    """从 data_id 后缀推断配置格式：json / yaml / None（无后缀纯文本）。"""
    ext = data_id.rsplit(".", 1)[-1].lower() if "." in data_id else ""
    if ext == "json":
        return "json"
    if ext in ("yaml", "yml"):
        return "yaml"
    return None


def _validate_content(data_id: str, content: str | None) -> None:
    """按 data_id 后缀校验内容格式；非法直接拒绝提交。无后缀/纯文本不校验。"""
    if not content:
        return
    fmt = _infer_format(data_id)
    if fmt is None:
        return
    if fmt == "json":
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            raise BizException(40000, f"配置内容不是合法 JSON: {e}")
        return
    try:
        import yaml
    except ImportError:
        logger.warning("未安装 PyYAML，跳过 YAML 格式校验")
        return
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise BizException(40000, f"配置内容不是合法 YAML: {e}")


async def _current_config(client, data_id: str, group: str) -> dict | None:
    """查 Nacos 当前配置（含 id/md5/content），不存在返回 None。"""
    result = await _nacos_call(client.list_configs, data_id=data_id, group=group, page_size=1)
    items = (result or {}).get("pageItems") or []
    return items[0] if items else None


async def _apply_update(session: AsyncSession, req: dict[str, Any], **fields: Any) -> None:
    """更新申请单并把新值同步回内存行，保证调用方拿到的就是最新状态。"""
    await ConfigDao.update_request(session, req["id"], **fields)
    req.update(fields)
    await session.commit()


async def create_request(
    session: AsyncSession,
    *,
    namespace: str,
    group_id: str,
    data_id: str,
    domain: str,
    op_type: int,
    title: str | None,
    content_new: str | None,
    content_format: str = "json",
    reason: str | None = None,
) -> dict[str, Any]:
    """发起配置变更申请（增/改/删）。回滚请用 create_rollback。"""
    if op_type not in (OP_ADD, OP_MODIFY, OP_DELETE):
        raise BizException(40000, "不支持的操作类型")
    if op_type == OP_ADD and not content_new:
        raise BizException(40000, "新增配置必须提供内容")
    if op_type == OP_MODIFY and not content_new:
        raise BizException(40000, "修改配置必须提供内容")
    if op_type == OP_DELETE:
        content_new = None  # 删除无新内容
    _validate_content(data_id, content_new)

    client = get_config_center_client()
    cur = await _current_config(client, data_id, group_id)
    if op_type == OP_ADD and cur:
        raise BizException(40000, "配置已存在，请改用修改")
    if op_type in (OP_MODIFY, OP_DELETE) and not cur:
        raise BizException(40400, "配置不存在，无法修改/删除")

    req = await ConfigDao.add_request(
        session,
        namespace=namespace, group_id=group_id, data_id=data_id, domain=domain,
        op_type=op_type, title=title, content_new=content_new,
        content_format=content_format, reason=reason,
        old_config_id=cur["id"] if cur else None,
        old_config_md5=cur["md5"] if cur else None,
        applicant_user_id=_operator(), status=ST_PENDING,
    )
    await session.commit()
    logger.info(f"配置变更申请已创建: id={req['id']} op={_OP_NAME[op_type]} data_id={data_id}")
    return req


async def create_rollback(
    session: AsyncSession,
    *,
    namespace: str,
    group_id: str,
    data_id: str,
    domain: str,
    src_history_nid: int,
    title: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """发起回滚申请：用指定历史版本（src_history_nid）的内容作为拟下发内容。"""
    client = get_config_center_client()
    hist = await _nacos_call(client.get_history, data_id, src_history_nid, group_id)
    if not hist:
        raise BizException(40400, "历史记录不存在")
    cur = await _current_config(client, data_id, group_id)
    _validate_content(data_id, hist.get("content"))
    req = await ConfigDao.add_request(
        session,
        namespace=namespace, group_id=group_id, data_id=data_id, domain=domain,
        op_type=OP_ROLLBACK, title=title or f"回滚至历史 nid={src_history_nid}",
        content_new=hist.get("content"), content_format="json", reason=reason,
        old_config_id=cur["id"] if cur else None,
        old_config_md5=cur["md5"] if cur else None,
        src_history_nid=src_history_nid,
        applicant_user_id=_operator(), status=ST_PENDING,
    )
    await session.commit()
    logger.info(f"回滚申请已创建: id={req['id']} data_id={data_id} src_nid={src_history_nid}")
    return req


async def review(
    session: AsyncSession,
    *,
    request_id: int,
    action: int,
    comment: str | None = None,
) -> dict[str, Any]:
    """复核：通过（置为待执行 APPROVED）或驳回。悲观锁保证状态只迁移一次。"""
    if action not in (RV_PASS, RV_REJECT):
        raise BizException(40000, "不支持的复核动作")

    req = await ConfigDao.get_request(session, request_id, for_update=True)
    if req is None:
        raise BizException(40400, "申请不存在")
    if req["status"] != ST_PENDING:
        raise BizException(40000, f"申请已处理（status={req['status']}），不可重复复核")

    reviewer_user_id = _operator()
    new_status = ST_REJECTED if action == RV_REJECT else ST_APPROVED
    await ConfigDao.add_review(
        session,
        request_id=request_id,
        reviewer_user_id=reviewer_user_id,
        action=action,
        comment=comment,
    )
    await _apply_update(
        session, req, status=new_status, reviewer_user_id=reviewer_user_id
    )
    verdict = "驳回" if action == RV_REJECT else "通过(待执行)"
    logger.info(f"配置申请已{verdict}: id={request_id} reviewer_user_id={reviewer_user_id}")
    return req


async def execute_request(
    session: AsyncSession,
    *,
    request_id: int,
    operator: str | None = None,
) -> dict[str, Any]:
    """执行已通过的申请：写 Nacos（带 CAS）+ 回填历史 nid。"""
    executor = operator or _operator()
    req = await ConfigDao.get_request(session, request_id, for_update=True)
    if req is None:
        raise BizException(40400, "申请不存在")
    if req["status"] != ST_APPROVED:
        raise BizException(
            40000, f"申请未处于待执行状态（status={req['status']}），请先通过复核"
        )

    client = get_config_center_client()
    cur = await _current_config(client, req["data_id"], req["group_id"])
    if req["old_config_md5"] and cur and cur.get("md5") != req["old_config_md5"]:
        # 期间被他人改过：直接判驳回，避免用旧 CAS 覆盖别人的修改
        await _apply_update(session, req, status=ST_REJECTED)
        raise BizException(40900, "配置已被他人修改，执行被拒绝，请刷新后重新申请")

    op = req["op_type"]
    try:
        if op == OP_DELETE:
            ok = await _nacos_call(
                client.remove_config, req["data_id"], req["group_id"],
                cas_md5=cur["md5"] if cur else None,
            )
        elif op == OP_ROLLBACK:
            ok = await _nacos_call(
                client.rollback, req["data_id"], req["src_history_nid"], req["group_id"]
            )
        else:  # OP_ADD / OP_MODIFY
            ok = await _nacos_call(
                client.publish_config, req["data_id"], req["content_new"] or "",
                req["group_id"], cas_md5=cur["md5"] if cur else None,
            )
    except ConfigCenterError as e:
        await session.rollback()
        raise BizException(50200, f"Nacos 执行失败: {e}")

    if not ok:
        await session.rollback()
        raise BizException(50200, "Nacos 执行返回失败（可能被并发修改）")

    new_nid, old_nid = await _resolve_history_nids(
        client, req["data_id"], req["group_id"], req["old_config_md5"]
    )
    await _apply_update(
        session,
        req,
        status=ST_EXECUTED,
        nacos_history_nid=new_nid,
        old_history_nid=old_nid,
    )
    logger.info(
        f"配置申请已执行: id={req['id']} op={_OP_NAME.get(op, op)} "
        f"executor={executor} new_nid={new_nid} old_nid={old_nid}"
    )

    if req["group_id"] == ConfigGroup.PROMPT.value:
        await refresh_prompt(req["data_id"])

    if new_nid is None:
        await sync_history_nids(session, request_id=req["id"])
    return req


async def _resolve_history_nids(
    client, data_id: str, group: str, old_md5: str | None
) -> tuple[int | None, int | None]:
    """执行成功后从 Nacos 历史里解析 new/old 两个 nid。"""
    history = await _nacos_call(client.list_history, data_id, group, page_size=10)
    items = (history or {}).get("pageItems") or []
    new_nid = max((it["nid"] for it in items if "nid" in it), default=None)
    old_nid = next((it["nid"] for it in items if it.get("md5") == old_md5), None)
    return new_nid, old_nid


async def sync_history_nids(
    session: AsyncSession, *, request_id: int
) -> dict[str, Any] | None:
    """补偿：重新从 Nacos 拉历史，回填 old_history_nid / nacos_history_nid。"""
    req = await get_request(session, request_id=request_id)
    if req["status"] != ST_EXECUTED:
        return req
    client = get_config_center_client()
    new_nid, old_nid = await _resolve_history_nids(
        client, req["data_id"], req["group_id"], req["old_config_md5"]
    )
    if req["nacos_history_nid"] != new_nid or req["old_history_nid"] != old_nid:
        await _apply_update(
            session, req, nacos_history_nid=new_nid, old_history_nid=old_nid
        )
        logger.info(
            f"配置历史 nid 补偿完成: id={req['id']} new_nid={new_nid} old_nid={old_nid}"
        )
    return req


async def list_requests(
    session: AsyncSession,
    *,
    status: int | None = None,
    domain: str | None = None,
    applicant_user_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """申请列表（查询数据库，系统级无 tenant）。"""
    return await ConfigDao.list_requests(
        session,
        status=status,
        domain=domain,
        applicant_user_id=applicant_user_id,
        page=page,
        page_size=page_size,
    )


async def get_request(session: AsyncSession, *, request_id: int) -> dict[str, Any]:
    req = await ConfigDao.get_request(session, request_id)
    if req is None:
        raise BizException(40400, "申请不存在")
    return req


async def get_request_detail(session: AsyncSession, *, request_id: int) -> dict[str, Any]:
    """申请详情：返回申请字段 + 旧内容（实时从 Nacos 拉当前态）+ 新内容，供前端 diff。"""
    req = await get_request(session, request_id=request_id)
    old_content: str | None = None
    if req["op_type"] != OP_ADD:
        client = get_config_center_client()
        try:
            old_content = await _nacos_call(
                client.get_config, req["data_id"], req["group_id"]
            )
        except ConfigCenterError:
            old_content = None
    return {
        "id": req["id"], "namespace": req["namespace"], "group_id": req["group_id"],
        "data_id": req["data_id"], "domain": req["domain"], "op_type": req["op_type"],
        "title": req["title"], "content_format": req["content_format"],
        "content_new": req["content_new"], "old_content": old_content,
        "status": req["status"], "applicant_user_id": req["applicant_user_id"],
        "reviewer_user_id": req["reviewer_user_id"],
        "reason": req["reason"], "src_history_nid": req["src_history_nid"],
        "nacos_history_nid": req["nacos_history_nid"],
        "create_at": req["create_at"], "updated_at": req["updated_at"],
    }
