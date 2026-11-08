"""菜单 DAO：菜单下发数据源（按 scope 过滤 + 组装树）。

菜单只控制入口显隐，不是安全边界；接口侧仍须挂 require_scope。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.data.sql import execute_write, fetch_all, fetch_page, fetch_value, session_scope
from backend.observability.exception import BizException, ErrCode

_LIST_VISIBLE = text(
    "SELECT id, name, path, icon, parent_id, sort_order, visible, scope "
    "FROM agent_menu WHERE visible = true ORDER BY sort_order, id"
)

_MENU_COLUMNS = (
    "SELECT id, name, path, icon, parent_id, sort_order, visible, scope FROM agent_menu"
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
        """按 scope 过滤可见菜单：scope 为空（登录即可见）/ scope ∈ scopes（精确匹配）。"""
        allowed = set(scopes or [])
        out: list[dict[str, Any]] = []
        for r in rows:
            scope = r.get("scope")
            if scope is None or scope in allowed:
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
    async def build(scopes: list[str]) -> list[dict[str, Any]]:
        rows = await MenuDao.list_visible()
        rows = MenuDao.filter_by_scopes(rows, list(scopes or []))
        return MenuDao.build_tree(rows)

    @staticmethod
    async def list_paged(
        page: int = 1,
        page_size: int = 50,
        *,
        name: str | None = None,
        path: str | None = None,
        scope: str | None = None,
        visible: bool | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """菜单分页；名称/路径/权限点均为 ILIKE 模糊匹配。"""
        conds: list[str] = []
        params: dict[str, Any] = {}

        keyword = (name or "").strip()
        if keyword:
            conds.append("name ILIKE :name")
            params["name"] = f"%{keyword}%"

        path_keyword = (path or "").strip()
        if path_keyword:
            conds.append("path ILIKE :path")
            params["path"] = f"%{path_keyword}%"

        scope_keyword = (scope or "").strip()
        if scope_keyword:
            conds.append("COALESCE(scope, '') ILIKE :scope")
            params["scope"] = f"%{scope_keyword}%"

        if visible is not None:
            conds.append("visible = :visible")
            params["visible"] = visible

        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        list_sql = text(
            f"{_MENU_COLUMNS} {where} ORDER BY parent_id, sort_order, id "
            "LIMIT :limit OFFSET :offset"
        )
        count_sql = text(f"SELECT count(*) FROM agent_menu {where}")

        async with session_scope() as session:
            return await fetch_page(
                session, list_sql, count_sql, params, page=page, page_size=page_size
            )

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

    @staticmethod
    async def set_visible(menu_id: int, visible: bool) -> int:
        """仅切换菜单显隐（status 端点用），其余列不变。"""
        async with session_scope() as session:
            return await execute_write(
                session,
                text("UPDATE agent_menu SET visible=:visible WHERE id=:id"),
                {"id": menu_id, "visible": visible},
            )
