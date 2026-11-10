"""配置中心审批流服务：申请/复核/执行/回滚，Nacos 写仅审批后触发并带 casMd5 乐观锁。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.config_center.groups import ConfigGroup
from backend.common.config_center import ConfigCenterError, get_config_center_client
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
ST_WITHDRAWN = 4  # 申请人主动撤回（仅限待复核）

# 复核动作
RV_PASS = 1
RV_REJECT = 2

_OP_NAME = {OP_ADD: "新增", OP_MODIFY: "修改", OP_DELETE: "删除", OP_ROLLBACK: "回滚"}
_RV_NAME = {RV_PASS: "通过", RV_REJECT: "驳回"}


def _operator() -> int | None:
    return user_id_ctx.get()


async def _nacos_call(fn, *args, **kwargs):
    """调用 Nacos 客户端方法（已为 async，直接 await）。"""
    return await fn(*args, **kwargs)


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
        logger.exception("未安装 PyYAML，跳过 YAML 格式校验")
        return
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise BizException(40000, f"配置内容不是合法 YAML: {e}")


async def _current_config(client, data_id: str, group: str) -> dict | None:
    """查 Nacos 当前配置（含 id/md5/content/type），不存在返回 None。"""
    result = await _nacos_call(
        client.list_configs, data_id=data_id, group=group, page_size=1, with_meta=True
    )
    items = (result or {}).get("pageItems") or []
    return items[0] if items else None


async def _apply_update(session: AsyncSession, req: dict[str, Any], **fields: Any) -> None:
    """更新申请单并把新值同步回内存行，保证调用方拿到的就是最新状态。

    不在此处 commit——事务由 session_scope（session.begin()）在块退出时统一提交。
    """
    await ConfigDao.update_request(session, req["id"], **fields)
    req.update(fields)


async def create_request(
    session: AsyncSession,
    *,
    namespace: str,
    group_id: str,
    data_id: str,
    op_type: int,
    title: str | None,
    content_new: str | None,
    content_format: str | None = None,
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
    if op_type == OP_DELETE:
        # 删除不发布到 Nacos，仅记录类型用于展示：优先 Nacos 当前配置真实 type，
        # 其次请求传入的真实类型，再回落 text
        content_format = (
            (cur.get("type") if isinstance(cur, dict) else None) or content_format or "text"
        )

    req = await ConfigDao.add_request(
        session,
        namespace=namespace,
        group_id=group_id,
        data_id=data_id,
        op_type=op_type,
        title=title,
        content_new=content_new,
        content_format=content_format,
        reason=reason,
        src_history_nid=None,
        applicant_user_id=_operator(),
        status=ST_PENDING,
    )
    logger.info(f"配置变更申请已创建: id={req['id']} op={_OP_NAME[op_type]} data_id={data_id}")
    return req


async def create_rollback(
    session: AsyncSession,
    *,
    namespace: str,
    group_id: str,
    data_id: str,
    src_history_nid: int,
    title: str | None = None,
    reason: str | None = None,
    content_format: str | None = None,
) -> dict[str, Any]:
    """发起回滚申请：用指定历史版本（src_history_nid）的内容作为拟下发内容。"""
    client = get_config_center_client()
    hist = await _nacos_call(client.get_history, data_id, src_history_nid, group_id)
    if not hist:
        raise BizException(40400, "历史记录不存在")
    _validate_content(data_id, hist.get("content"))
    req = await ConfigDao.add_request(
        session,
        namespace=namespace,
        group_id=group_id,
        data_id=data_id,
        op_type=OP_ROLLBACK,
        title=title or f"回滚至历史 nid={src_history_nid}",
        # 回滚内容类型优先用历史版本真实 type；历史详情缺 type 时回落请求传入的真实类型，再回落 text
        content_new=hist.get("content"),
        content_format=hist.get("type") or content_format or "text",
        reason=reason,
        src_history_nid=src_history_nid,
        applicant_user_id=_operator(),
        status=ST_PENDING,
    )
    logger.info(f"回滚申请已创建: id={req['id']} data_id={data_id} src_nid={src_history_nid}")
    return req


async def review(
    session: AsyncSession,
    *,
    request_id: int,
    action: int,
    comment: str | None = None,
) -> dict[str, Any]:
    """复核：驳回直接结束；通过则「审批即执行」——登记复核后立刻写 Nacos。

    悲观锁保证状态只迁移一次。通过分支在 session.begin() 事务内调用 execute_request
    写 Nacos：成功→块退出自动提交（含复核记录与状态推进），Nacos 失败→异常冒泡、
    session.begin() 自动回滚整笔事务，申请回到待复核原状，可重新点击审批。
    """
    if action not in (RV_PASS, RV_REJECT):
        raise BizException(40000, "不支持的复核动作")

    req = await ConfigDao.get_request(session, request_id, for_update=True)
    if req is None:
        raise BizException(40400, "申请不存在")
    if req["status"] != ST_PENDING:
        raise BizException(40000, f"申请已处理（status={req['status']}），不可重复复核")

    reviewer_user_id = _operator()
    await ConfigDao.add_review(
        session,
        approval_id=request_id,
        reviewer_user_id=reviewer_user_id,
        action=action,
        comment=comment,
    )
    if action == RV_REJECT:
        await _apply_update(
            session,
            req,
            status=ST_REJECTED,
            reviewer_user_id=reviewer_user_id,
            effective_at=True,
        )
        logger.info(f"配置申请已驳回: id={request_id} reviewer_user_id={reviewer_user_id}")
        return req

    # 通过（审批即执行）：事务内先写 Nacos，成功由 session.begin() 自动提交；
    # Nacos 抛异常则冒泡，session.begin() 自动回滚整笔事务（含复核记录）。
    await _apply_update(session, req, status=ST_APPROVED, reviewer_user_id=reviewer_user_id)
    executed = await execute_request(session, request_id=request_id)
    logger.info(f"配置申请已审批并执行: id={request_id} reviewer_user_id={reviewer_user_id}")
    return executed


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
        raise BizException(40000, f"申请未处于待执行状态（status={req['status']}），请先通过复核")

    client = get_config_center_client()
    cur = await _current_config(client, req["data_id"], req["group_id"])
    op = req["op_type"]
    if op in (OP_MODIFY, OP_DELETE) and not cur:
        # 配置在执行前已被删除：拒绝执行，避免误建/误删（异常冒泡由 session.begin() 回滚）
        raise BizException(40400, "配置已不存在，无法执行（可能已在复核前被删除）")

    try:
        if op == OP_DELETE:
            ok = await _nacos_call(
                client.remove_config,
                req["data_id"],
                req["group_id"],
                cas_md5=cur["md5"] if cur else None,
            )
        else:  # OP_ADD / OP_MODIFY / OP_ROLLBACK：统一用申请单已存内容发布，类型随申请记录
            ok = await _nacos_call(
                client.publish_config,
                req["data_id"],
                req["content_new"] or "",
                req["group_id"],
                content_format=req["content_format"] or "text",
                cas_md5=cur["md5"] if cur else None,
            )
    except ConfigCenterError as e:
        # Nacos 调用失败：异常冒泡，整笔事务由 session.begin() 自动回滚
        raise BizException(50200, f"Nacos 执行失败: {e}")

    if not ok:
        # Nacos 返回失败（可能被并发修改）：同样冒泡回滚
        raise BizException(50200, "Nacos 执行返回失败（可能被并发修改）")

    new_nid, old_nid = await _resolve_history_nids(
        client, req["data_id"], req["group_id"], cur["md5"] if cur else None
    )
    await _apply_update(
        session,
        req,
        status=ST_EXECUTED,
        nacos_history_nid=new_nid,
        effective_at=True,
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
    """执行成功后从 Nacos 历史里解析 new/old 两个 nid。

    Nacos 历史列表返回的 nid 是字符串（如 "126"），统一转 int 后再落库，
    否则写入 BIGINT 列会触发 asyncpg 类型错误；并避免 max 按字典序误选版本。
    """
    history = await _nacos_call(client.list_history, data_id, group, page_size=10)
    items = (history or {}).get("pageItems") or []

    def _nid_of(it: dict) -> int | None:
        raw = it.get("nid")
        return int(raw) if raw is not None else None

    nids = [n for n in (_nid_of(it) for it in items) if n is not None]
    new_nid = max(nids, default=None)
    old_nid = next(
        (_nid_of(it) for it in items if it.get("md5") == old_md5 and it.get("nid") is not None),
        None,
    )
    return new_nid, old_nid


async def sync_history_nids(session: AsyncSession, *, request_id: int) -> dict[str, Any] | None:
    """补偿：重新从 Nacos 拉历史，回填 old_history_nid / nacos_history_nid。"""
    req = await get_request(session, request_id=request_id)
    if req["status"] != ST_EXECUTED:
        return req
    client = get_config_center_client()
    cur = await _current_config(client, req["data_id"], req["group_id"])
    new_nid, _ = await _resolve_history_nids(
        client, req["data_id"], req["group_id"], cur["md5"] if cur else None
    )
    if req["nacos_history_nid"] != new_nid:
        await _apply_update(session, req, nacos_history_nid=new_nid)
        logger.info(f"配置历史 nid 补偿完成: id={req['id']} new_nid={new_nid}")
    return req


async def list_requests(
    session: AsyncSession,
    *,
    status: int | None = None,
    group_id: str | None = None,
    applicant_user_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """审批单列表（查询数据库，系统级无 tenant）。返回前把申请人/复核人 id 解析成 username。"""
    rows, total = await ConfigDao.list_requests(
        session,
        status=status,
        group_id=group_id,
        applicant_user_id=applicant_user_id,
        page=page,
        page_size=page_size,
    )
    names = await ConfigDao.resolve_usernames(
        session,
        [r["applicant_user_id"] for r in rows] + [r["reviewer_user_id"] for r in rows],
    )
    for r in rows:
        r["applicant_name"] = names.get(r["applicant_user_id"])
        r["reviewer_name"] = names.get(r["reviewer_user_id"])
    return rows, total


async def get_request(session: AsyncSession, *, request_id: int) -> dict[str, Any]:
    req = await ConfigDao.get_request(session, request_id)
    if req is None:
        raise BizException(40400, "申请不存在")
    return req


async def withdraw_request(
    session: AsyncSession,
    *,
    request_id: int,
    user_id: int,
) -> dict[str, Any]:
    """撤回自己的待复核申请（config:update，所有角色可操作）。

    只有申请人本人、且申请仍处于待复核（ST_PENDING）才能撤回；复核/执行后不可撤。
    """
    req = await ConfigDao.get_request(session, request_id, for_update=True)
    if req is None:
        raise BizException(40400, "申请不存在")
    if req["status"] != ST_PENDING:
        raise BizException(40000, "仅待复核申请可撤回")
    if req["applicant_user_id"] != user_id:
        raise BizException(40300, "只能撤回自己的申请")
    await _apply_update(session, req, status=ST_WITHDRAWN, effective_at=True)
    logger.info(f"配置申请已撤回: id={request_id} user_id={user_id}")
    return req


async def get_request_detail(session: AsyncSession, *, request_id: int) -> dict[str, Any]:
    """申请详情：返回申请字段 + 旧内容（实时从 Nacos 拉当前态）+ 新内容，供前端 diff。"""
    req = await get_request(session, request_id=request_id)
    names = await ConfigDao.resolve_usernames(
        session, [req["applicant_user_id"], req["reviewer_user_id"]]
    )
    old_content: str | None = None
    if req["op_type"] != OP_ADD:
        client = get_config_center_client()
        try:
            old_content = await _nacos_call(client.get_config, req["data_id"], req["group_id"])
        except ConfigCenterError:
            old_content = None
    return {
        "id": req["id"],
        "namespace": req["namespace"],
        "group_id": req["group_id"],
        "data_id": req["data_id"],
        "op_type": req["op_type"],
        "title": req["title"],
        "content_format": req["content_format"],
        "content_new": req["content_new"],
        "old_content": old_content,
        "status": req["status"],
        "applicant_user_id": req["applicant_user_id"],
        "applicant_name": names.get(req["applicant_user_id"]),
        "reviewer_user_id": req["reviewer_user_id"],
        "reviewer_name": names.get(req["reviewer_user_id"]),
        "reason": req["reason"],
        "src_history_nid": req["src_history_nid"],
        "nacos_history_nid": req["nacos_history_nid"],
        "effective_at": req.get("effective_at"),
        "create_at": req["create_at"],
        "updated_at": req["updated_at"],
    }


async def get_reviews(session: AsyncSession, *, approval_id: int) -> list[dict[str, Any]]:
    """某审批单的复核记录（按时间正序），并把复核人 id 解析成 username。"""
    reviews = await ConfigDao.list_reviews(session, approval_id=approval_id)
    names = await ConfigDao.resolve_usernames(session, [r["reviewer_user_id"] for r in reviews])
    for r in reviews:
        r["reviewer_name"] = names.get(r["reviewer_user_id"])
    return reviews


async def list_review_logs(
    session: AsyncSession, *, page: int = 1, page_size: int = 20
) -> tuple[list[dict[str, Any]], int]:
    """审核日志：全量复核记录，附带复核人用户名与动作中文名（只读列表）。"""
    rows, total = await ConfigDao.list_all_reviews(session, page=page, page_size=page_size)
    for r in rows:
        r["action_name"] = _RV_NAME.get(r["action"], str(r["action"]))
        op_type = r.get("op_type")
        r["op_type_name"] = _OP_NAME.get(op_type, op_type)
    return rows, total
