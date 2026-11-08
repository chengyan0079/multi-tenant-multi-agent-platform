"""消费端零信任鉴权单测：严格按租户 id 校验（知识库按租户隔离）。

规则：
- 消息必须携带有效 tenant_id，tenant_id=None（平台级 / 未指定）直接拒绝；
- 用户在 (user_id, tenant_id) 有身份 → 校验 scopes；
- 用户在租户无直接身份但为超管 → 对任一租户放行（超管全局权）；
- 二者皆无 → 拒绝。
"""
from __future__ import annotations

import pytest

from backend.broker import security as sec
from backend.data.milvus.store import _tenant_key
from backend.observability.exception import BizException
from backend.security.rbac import Identity


def _identity(*, user_id: int, tenant_id: int | None, scopes: list[str], super_admin: bool = False):
    return Identity(
        user_id=user_id,
        tenant_id=tenant_id,
        role_name="admin" if super_admin else "student",
        scopes=scopes,
        is_super_admin=super_admin,
    )


@pytest.mark.asyncio
async def test_missing_tenant_id_rejected(monkeypatch) -> None:
    """严格按租户 id 校验：tenant_id 为空（平台级）直接拒绝，不调用任何身份解析。"""
    calls = {"identity": 0, "super": 0}

    async def fake_identity(uid: int, tid: int):
        calls["identity"] += 1
        return None

    async def fake_super(uid: int):
        calls["super"] += 1
        return None

    monkeypatch.setattr(sec.RbacService, "resolve_identity", staticmethod(fake_identity))
    monkeypatch.setattr(sec.RbacService, "resolve_super_admin", staticmethod(fake_super))

    with pytest.raises(BizException, match="缺少归属租户"):
        await sec.authorize_task(1, None, ["file:upload"])
    assert calls == {"identity": 0, "super": 0}


@pytest.mark.asyncio
async def test_super_admin_any_tenant_allowed(monkeypatch) -> None:
    """用户在租户无直接分配，但为超管 → 对任一具体租户放行（租户隔离 + 超管全局权）。"""

    async def none_identity(uid: int, tid: int):
        return None

    async def super_identity(uid: int):
        return _identity(user_id=uid, tenant_id=None, scopes=[], super_admin=True)

    monkeypatch.setattr(sec.RbacService, "resolve_identity", staticmethod(none_identity))
    monkeypatch.setattr(sec.RbacService, "resolve_super_admin", staticmethod(super_identity))

    await sec.authorize_task(1, 7, ["file:upload"])


@pytest.mark.asyncio
async def test_tenant_user_ok(monkeypatch) -> None:
    async def ok_identity(uid: int, tid: int):
        return _identity(user_id=uid, tenant_id=tid, scopes=["file:upload"], super_admin=False)

    monkeypatch.setattr(sec.RbacService, "resolve_identity", staticmethod(ok_identity))

    await sec.authorize_task(3, 7, ["file:upload"])


@pytest.mark.asyncio
async def test_tenant_user_requires_scope(monkeypatch) -> None:
    async def partial_identity(uid: int, tid: int):
        return _identity(user_id=uid, tenant_id=tid, scopes=["file:page"], super_admin=False)

    monkeypatch.setattr(sec.RbacService, "resolve_identity", staticmethod(partial_identity))

    with pytest.raises(BizException, match="缺少权限点"):
        await sec.authorize_task(3, 7, ["file:upload"])


@pytest.mark.asyncio
async def test_no_identity_rejected(monkeypatch) -> None:
    async def none_identity(uid: int, tid: int):
        return None

    async def none_super(uid: int):
        return None

    monkeypatch.setattr(sec.RbacService, "resolve_identity", staticmethod(none_identity))
    monkeypatch.setattr(sec.RbacService, "resolve_super_admin", staticmethod(none_super))

    with pytest.raises(BizException, match="无身份"):
        await sec.authorize_task(3, 7, ["file:upload"])


def test_tenant_key_normalizes_platform_to_zero() -> None:
    """写入用 tenant_id or 0，检索必须一致，否则会召回不到对应分区。

    注：业务层已保证上传 / 入队必带有效 tenant_id，此函数仅作最后兜底，
    避免极端 None 拼出 `tenant_id == "None"` 而非 `"0"`。
    """
    assert _tenant_key(None) == "0"
    assert _tenant_key(0) == "0"
    assert _tenant_key(7) == "7"
    assert _tenant_key("7") == "7"
