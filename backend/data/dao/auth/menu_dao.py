"""菜单 DAO：菜单下发数据源（按 scope 过滤 + 组装树，见设计文档 §7）。

菜单只控制入口显隐，不是安全边界；接口侧仍须挂 require_scope。
过滤规则（§7.2）：
  1. visible = true
  2. scope IS NULL OR scope ∈ 用户 scopes OR 用户 scopes 含 "*"
  3. 父菜单可见（parent_id = 0 视为顶级）
  4. 超管：path ∈ SUPER_ADMIN_MENU_PATHS（由调用方用 rbac.SUPER_ADMIN_MENU_PATHS 约束）
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.data.sql import execute_write, fetch_all, fetch_value, session_scope
from backend.observability.exception import BizException, ErrCode
from backend.security.rbac import SUPER_ADMIN_MENU_PATHS

_LIST_VISIBLE = text(
    "SELECT id, name, path, icon, parent_id, sort_order, visible, scope "
    "FROM agent_menu WHERE visible = true ORDER BY sort_order, id"
)

_LIST_ALL = text(
    "SELECT id, name, path, icon, parent_id, sort_order, visible, scope "
    "FROM agent_menu ORDER BY parent_id, sort_order, id"
)
_INSERT_MENU = text(
    "INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) "
    "VALUES (:name, :path, :icon, :parent_id, :sort_order, :visible, :scope) "
    "RETURNING id"
)
_UPDATE_MENU = text(
    "UPDATE agent_menu SET name = :name, path = :path, icon = :icon, parent_id = :parent_id, "
    "sort_order = :sort_order, visible = :visible, scope = :scope WHERE id = :id"
)
_DELETE_MENU = text("DELETE FROM agent_menu WHERE id = :id")
_CHILD_COUNT = text("SELECT count(*) FROM agent_menu WHERE parent_id = :parent_id")


class MenuDao:
    """菜单读写：可见菜单查询、按 scope 过滤、组装树。"""

    @staticmethod
    async def list_visible() -> list[dict[str, Any]]:
        """全部可见菜单（按 sort_order 升序），由调用方按 scope 过滤后再组装树。"""
        async with session_scope() as session:
            return await fetch_all(session, _LIST_VISIBLE)

    @staticmethod
    def filter_by_scopes(
        rows: list[dict[str, Any]], scopes: list[str]
    ) -> list[dict[str, Any]]:
        """按 scope 过滤可见菜单：scope 为空（登录即可见）/ scope ∈ scopes / scopes 含 '*'。"""
        allowed = set(scopes or [])
        out: list[dict[str, Any]] = []
        for r in rows:
            scope = r.get("scope")
            if scope is None or scope in allowed or "*" in allowed:
                out.append(r)
        return out

    @staticmethod
    def build_tree(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把扁平菜单组装为树（parent_id=0 视为顶级）。"""
        by_id = {r["id"]: {**r, "children": []} for r in rows}
        roots: list[dict[str, Any]] = []
        for node in by_id.values():
            parent = by_id.get(node.get("parent_id") or 0)
            if parent is None or parent is node:
                roots.append(node)
            else:
                parent["children"].append(node)  # type: ignore[typeddict-item]
        return roots

    @staticmethod
    async def build(
        scopes: list[str], is_super_admin: bool
    ) -> list[dict[str, Any]]:
        """按身份组装菜单树（见 §7.2）。

        - 超管：只下发 SUPER_ADMIN_MENU_PATHS 白名单内的基建菜单（按根路径匹配，
          自动包含其下所有子菜单）；业务菜单（/dashboard、/sessions、/qa 等）不以
          白名单前缀开头，自然被排除；
        - 其余：按 scope 过滤（scope 为空 / 命中 / 含 '*'）后再成树。
        """
        rows = await MenuDao.list_visible()
        if is_super_admin:
            # 根路径精确匹配 + 后代路径（startswith 前缀）一并下发，使子菜单可见
            rows = [
                r
                for r in rows
                if any(
                    r["path"] == p or r["path"].startswith(p + "/")
                    for p in SUPER_ADMIN_MENU_PATHS
                )
            ]
        else:
            rows = MenuDao.filter_by_scopes(rows, scopes)
        return MenuDao.build_tree(rows)

    @staticmethod
    async def list_all() -> list[dict[str, Any]]:
        """全部菜单（含隐藏），供菜单管理使用。"""
        async with session_scope() as session:
            return await fetch_all(session, _LIST_ALL)

    @staticmethod
    async def create(
        *, name: str, path: str, icon: str, parent_id: int,
        sort_order: int, visible: bool, scope: str | None,
    ) -> int:
        """新建菜单，返回新 id（menu.id 为 BIGSERIAL，自动分配）。"""
        async with session_scope() as session:
            return int(
                await fetch_value(
                    session,
                    _INSERT_MENU,
                    {
                        "name": name, "path": path, "icon": icon,
                        "parent_id": parent_id, "sort_order": sort_order,
                        "visible": visible, "scope": scope,
                    },
                )
            )

    @staticmethod
    async def update(
        menu_id: int,
        *, name: str, path: str, icon: str, parent_id: int,
        sort_order: int, visible: bool, scope: str | None,
    ) -> int:
        """更新菜单字段。"""
        async with session_scope() as session:
            return await execute_write(
                session,
                _UPDATE_MENU,
                {
                    "id": menu_id, "name": name, "path": path, "icon": icon,
                    "parent_id": parent_id, "sort_order": sort_order,
                    "visible": visible, "scope": scope,
                },
            )

    @staticmethod
    async def delete(menu_id: int) -> int:
        """删除菜单；含子菜单时拒绝，避免产生孤儿节点。"""
        async with session_scope() as session:
            child_count = int(
                await fetch_value(session, _CHILD_COUNT, {"parent_id": menu_id})
            )
            if child_count:
                raise BizException(ErrCode.PARAM_ERROR, "该菜单含子菜单，请先处理子菜单")
            return await execute_write(session, _DELETE_MENU, {"id": menu_id})
