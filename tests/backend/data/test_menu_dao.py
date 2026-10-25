"""menu_dao.build 的菜单树组装测试（不连库，mock list_visible）。

覆盖 §7.2：
- 超管白名单按根路径匹配且自动包含子菜单，业务菜单（/qa、/sessions）被排除；
- 其余角色按 scope 过滤（含子菜单）。
"""
import pytest

from backend.data.dao.auth.menu_dao import MenuDao

_ROWS = [
    {"id": 1, "name": "审计日志", "path": "/audit", "icon": "", "parent_id": 0,
     "sort_order": 7, "visible": True, "scope": "audit:read"},
    {"id": 11, "name": "业务审计", "path": "/audit/operation", "icon": "", "parent_id": 1,
     "sort_order": 1, "visible": True, "scope": "audit:read"},
    {"id": 12, "name": "登录日志", "path": "/audit/login", "icon": "", "parent_id": 1,
     "sort_order": 2, "visible": True, "scope": "audit:read"},
    {"id": 6, "name": "配置中心", "path": "/config", "icon": "", "parent_id": 0,
     "sort_order": 6, "visible": True, "scope": "config:read"},
    {"id": 61, "name": "配置申请", "path": "/config/request", "icon": "", "parent_id": 6,
     "sort_order": 1, "visible": True, "scope": "config:read"},
    {"id": 9, "name": "咨询问答", "path": "/qa", "icon": "", "parent_id": 0,
     "sort_order": 9, "visible": True, "scope": "qa:read"},
    {"id": 2, "name": "会话运行", "path": "/sessions", "icon": "", "parent_id": 0,
     "sort_order": 2, "visible": True, "scope": "qa:read"},
]


def _all_paths(nodes):
    """递归收集整棵树的 path（含子菜单）。"""
    out = []
    for n in nodes:
        out.append(n["path"])
        out.extend(_all_paths(n.get("children", []) or []))
    return out


@pytest.fixture
def fake_rows(monkeypatch):
    async def _list():
        return list(_ROWS)

    monkeypatch.setattr(MenuDao, "list_visible", staticmethod(_list))


@pytest.mark.asyncio
async def test_super_admin_sees_children_but_not_business(fake_rows):
    tree = await MenuDao.build(scopes=[], is_super_admin=True)
    paths = set(_all_paths(tree))

    # 业务菜单被白名单挡掉（超管不看业务数据）
    assert "/qa" not in paths and "/sessions" not in paths
    # 白名单顶层 + 其下子菜单均可见
    assert "/audit" in paths and "/audit/operation" in paths
    assert "/config" in paths and "/config/request" in paths

    # 子菜单挂在对应父菜单下，而非成为独立顶级
    audit = next(n for n in tree if n["path"] == "/audit")
    child_paths = {c["path"] for c in (audit.get("children") or [])}
    assert "/audit/operation" in child_paths and "/audit/login" in child_paths


@pytest.mark.asyncio
async def test_tenant_admin_sees_by_scope(fake_rows):
    tree = await MenuDao.build(
        scopes=["audit:read", "rbac:read", "tenant:read", "qa:read"],
        is_super_admin=False,
    )
    paths = set(_all_paths(tree))
    assert "/audit/operation" in paths   # 有 audit:read
    assert "/qa" in paths                # 有 qa:read（业务菜单对租户管理员可见）
    assert "/config/request" not in paths  # 无 config:read，整支配置中心不出现
