"""menu 表模型（菜单下发数据源）。

设计说明：
- 登录后按当前租户角色的权限点过滤菜单，`scope=NULL` 表示登录即可见。
- 前端只认后端下发的菜单树，不再维护静态菜单。
- 与其余表遵循全库"逻辑外键"策略，不建物理外键。
"""
from sqlalchemy import BigInteger, Boolean, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.postgres.base import Base


class Menu(Base):
    """前端菜单（登录后按权限下发）。"""

    __tablename__ = "agent_menu"
    __table_args__ = {"comment": "前端菜单（登录后按权限下发）"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="菜单ID")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="菜单名称（前端展示）")
    path: Mapped[str] = mapped_column(String(128), nullable=False, comment="前端路由路径")
    icon: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("''"), comment="图标名（前端展示用，如 DashboardOutlined）"
    )
    parent_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0"), comment="父菜单ID（0=顶级菜单）"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), comment="排序号（升序）"
    )
    visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), comment="是否显示"
    )
    scope: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="访问该菜单所需权限点（NULL=登录即可见）"
    )
