"""
rbac - 角色/权限解析服务（设计文档 §9.1 ③ RBAC；身份由 JWT 解析，后端只做授权）

职责：
- resolve(user_id, tenant_id)：查 agent_user_tenant → agent_role → agent_role_permission，给出
  (role_name, scopes[])。后端据此做 require_role / require_scope，不信任 token 里的角色。
- ensure_default_roles()：幂等写入内置角色(student/teacher/admin)与权限点（全局，tenant 无关）。
- assign(user_id, tenant_id, role_id)：一人一租户一角色（PK 冲突即更新）。

权限点词汇（scope）：以 Scope 枚举（见下方）与 DEFAULT_ROLES 为**单一权威来源**；
新增权限点须在 Scope 中登记，任何散落字符串字面量都会在校验时立即报错。"*"（Scope.ALL）表示全部。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from backend.common.logger import get_logger
from backend.data.dao.auth.rbac_dao import RbacDao
from backend.data.dao.auth.user_dao import UserDao
from backend.data.sql.audit import SYSTEM_USER_ID

logger = get_logger("rbac")

class Scope(str, Enum):
    """权限点（scope）枚举：格式 `资源:动作`，资源为 agent/基础设施名，动作为增删改查等。

    单一权威来源；DEFAULT_ROLES 与各接口声明均须取自本枚举成员，
    拼写错误会在模块加载（DEFAULT_ROLES 引用）或鉴权（require_scope）时立即报错。
    "*"（ALL）表示全部权限。
    """

    # QA 问答
    QA_ASK = "qa:ask"
    QA_READ = "qa:read"
    # Interview 模拟面试
    INTERVIEW_ASK = "interview:ask"
    INTERVIEW_READ = "interview:read"
    # Resume 简历
    RESUME_ASK = "resume:ask"
    RESUME_UPLOAD = "resume:upload"
    RESUME_READ = "resume:read"
    # Exam 试卷
    EXAM_ASK = "exam:ask"
    EXAM_READ = "exam:read"
    EXAM_CREATE = "exam:create"
    EXAM_UPDATE = "exam:update"
    # Knowledge 知识库
    KNOWLEDGE_ASK = "knowledge:ask"
    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_UPLOAD = "knowledge:upload"
    KNOWLEDGE_DOWNLOAD = "knowledge:download"
    # Config 配置中心
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"
    CONFIG_REVIEW = "config:review"
    CONFIG_CREATE = "config:create"
    CONFIG_UPDATE = "config:update"
    CONFIG_DELETE = "config:delete"
    # Audit 审计日志（只读，不提供增删改）
    AUDIT_READ = "audit:read"
    # Agent 域（仅超管）
    AGENT_READ = "agent:read"
    AGENT_WRITE = "agent:write"
    AGENT_CREATE = "agent:create"
    AGENT_DELETE = "agent:delete"
    # Model 模型配置（仅超管）
    MODEL_READ = "model:read"
    MODEL_WRITE = "model:write"
    MODEL_CREATE = "model:create"
    MODEL_UPDATE = "model:update"
    MODEL_DELETE = "model:delete"
    # Auth 登录鉴权（登录 / 菜单 / 个人信息）
    AUTH_LOGIN = "auth:login"
    AUTH_READ = "auth:read"
    AUTH_WRITE = "auth:write"
    # User 用户管理（超管建号、改角色）
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    USER_CREATE = "user:create"
    USER_DELETE = "user:delete"
    # RBAC 用户与角色管理
    RBAC_READ = "rbac:read"
    RBAC_WRITE = "rbac:write"
    # Tenant 租户管理（仅超管）
    TENANT_READ = "tenant:read"
    TENANT_WRITE = "tenant:write"
    TENANT_CREATE = "tenant:create"
    TENANT_DELETE = "tenant:delete"
    # 全量
    ALL = "*"


class RoleName(str, Enum):
    """内置角色名（身份判定的唯一依据）。

    判定只看角色名与租户 `is_primary`，不看 `role_id` 数字：role_id 是入库用的
    代理业务键，库表重建、迁移、多环境种子都可能不同，写死在代码里必然出错。
    """

    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"
    TENANT_ADMIN = "tenant_admin"


def is_super_admin_role(role_name: str | None, tenant_is_primary: bool) -> bool:
    """是否为平台超管：主租户内的 admin 角色。

    两个条件缺一不可——任意租户里的 admin 都不算超管，
    避免历史脏数据把某个租户的管理员放大成全局超管。
    """
    return tenant_is_primary and role_name == RoleName.ADMIN.value


def is_tenant_admin_role(role_name: str | None) -> bool:
    """是否为租户管理员：只认角色名 tenant_admin。"""
    return role_name == RoleName.TENANT_ADMIN.value


# 内置角色目录：role_id(int 业务键) → (可读名 name, 权限点 scopes[])。
# 与 scripts/schema.sql 的 RBAC 默认数据保持一致；角色判断统一以 name 为准。
# 注意：本常量仅作为 ensure_default_roles() 的「种子源」写入数据库，
# 请求期授权解析一律以 agent_role_permission 表为准，本常量不参与任何兜底。
# scope 使用 Scope 枚举成员，确保任何拼写错误在加载期即暴露。
DEFAULT_ROLES: dict[int, tuple[str, list[Scope]]] = {
    1: ("student", [
        Scope.QA_ASK, Scope.QA_READ,
        Scope.INTERVIEW_ASK, Scope.INTERVIEW_READ,
        Scope.RESUME_ASK, Scope.RESUME_UPLOAD, Scope.RESUME_READ,
        Scope.EXAM_ASK, Scope.EXAM_READ,
        Scope.KNOWLEDGE_ASK, Scope.KNOWLEDGE_READ,
    ]),
    2: ("teacher", [
        Scope.QA_ASK, Scope.QA_READ, Scope.INTERVIEW_ASK,
        Scope.RESUME_UPLOAD, Scope.RESUME_READ,
        Scope.EXAM_CREATE, Scope.EXAM_READ, Scope.EXAM_UPDATE,
        Scope.KNOWLEDGE_ASK, Scope.KNOWLEDGE_READ,
        Scope.KNOWLEDGE_UPLOAD, Scope.KNOWLEDGE_DOWNLOAD,
    ]),
    3: ("admin", [
        Scope.AGENT_READ, Scope.AGENT_WRITE, Scope.AGENT_CREATE, Scope.AGENT_DELETE,
        Scope.MODEL_READ, Scope.MODEL_WRITE, Scope.MODEL_CREATE, Scope.MODEL_UPDATE, Scope.MODEL_DELETE,
        Scope.AUTH_LOGIN, Scope.AUTH_READ, Scope.AUTH_WRITE,
        Scope.RBAC_READ, Scope.RBAC_WRITE,
        Scope.USER_READ, Scope.USER_WRITE, Scope.USER_CREATE, Scope.USER_DELETE,
        Scope.TENANT_READ, Scope.TENANT_WRITE, Scope.TENANT_CREATE, Scope.TENANT_DELETE,
        Scope.CONFIG_READ, Scope.CONFIG_WRITE, Scope.CONFIG_REVIEW,
        Scope.AUDIT_READ,
    ]),
    # 4 已废弃：原 analyst（纯只读、无专属功能）没有实际职责，已删除；编号保留不复用
    # 租户管理员：本租户用户与角色 + 本租户审计（读）；不含 config / agent / model / tenant 域
    5: ("tenant_admin", [
        Scope.QA_READ, Scope.AUDIT_READ,
        Scope.RBAC_READ, Scope.RBAC_WRITE,
    ]),
}


@dataclass(frozen=True)
class Identity:
    """请求期身份快照：用户在某个租户内的角色名、权限点、是否主租户。

    超管/租户管理员都由本对象推导，下游不要再去比 role_id 数字。
    """

    user_id: int
    tenant_id: int | None
    role_name: str
    tenant_is_primary: bool
    scopes: list[str]

    @property
    def is_super_admin(self) -> bool:
        """平台超管：主租户 + admin 角色。"""
        return is_super_admin_role(self.role_name, self.tenant_is_primary)

    @property
    def is_tenant_admin(self) -> bool:
        """租户管理员：tenant_admin 角色。"""
        return is_tenant_admin_role(self.role_name)


# 超管可见菜单白名单（§7.2 第 4 条）：超管 scopes 含 "*"，但仍只下发基建菜单，
# 不暴露业务入口（/dashboard、/sessions 虽对 * 可见，但被本白名单挡掉）。
SUPER_ADMIN_MENU_PATHS: frozenset[str] = frozenset({
    "/tenants", "/rbac", "/audit", "/agents", "/tools", "/models", "/config",
})


class RbacService:
    """角色/权限解析（无状态，纯查库 + 内置目录）。"""

    @staticmethod
    async def ensure_default_roles() -> None:
        """幂等写入内置角色与权限点（全局，tenant 无关）。启动或租户开通时调用。

        启动期没有请求上下文，审计列显式记到系统身份（1001）。
        """
        roles = [
            (role_id, name, f"内置角色 {name}")
            for role_id, (name, _) in DEFAULT_ROLES.items()
        ]
        permissions = [
            (role_id, scope.value)
            for role_id, (_, scopes) in DEFAULT_ROLES.items()
            for scope in scopes
        ]
        new_roles, new_perms = await RbacDao.ensure_roles_and_permissions(
            roles, permissions, user_id=SYSTEM_USER_ID
        )
        logger.info(f"内置角色与权限点已确保（新增角色 {new_roles}、权限点 {new_perms}）")

    @staticmethod
    async def resolve_identity(user_id: int, tenant_id: int | None) -> Optional[Identity]:
        """解析请求期身份快照。以下情况一律返回 None，由调用方按未授权处理：

        - 该用户在该租户没有分配；
        - 分配指向的角色不存在（脏数据）；
        - 租户不存在或已停用。
        """
        if tenant_id is None:
            return None
        row = await RbacDao.get_identity(user_id, tenant_id)
        if row is None:
            return None
        return Identity(
            user_id=user_id,
            tenant_id=tenant_id,
            role_name=row["role_name"],
            tenant_is_primary=bool(row["tenant_is_primary"]),
            scopes=row["scopes"],
        )

    @staticmethod
    async def resolve(user_id: int, tenant_id: int | None) -> Optional[tuple[str, list[str]]]:
        """解析用户在租户内的 (角色名, 权限点[])。无分配返回 None（由调用方决定 403 或开发兜底）。"""
        identity = await RbacService.resolve_identity(user_id, tenant_id)
        if identity is None:
            return None
        return identity.role_name, identity.scopes

    @staticmethod
    async def authenticate(username: str, password: str) -> Optional[dict]:
        """登录认证：按 username 查 user 表并明文比对密码，返回 user 行或 None（设计文档 §2 / §3.2）。"""
        return await UserDao.authenticate(username, password)

    @staticmethod
    async def resolve_super_admin(user_id: int) -> Optional[Identity]:
        """超管分支解析：token 不含 tenant_id，仅按 user_id + 主租户 + admin 角色判定（§4.2 / §5.2）。

        命中返回 tenant_id=None / is_super_admin=True / scopes=种子里 admin 角色的具体权限点（无 "*"，菜单再由白名单收敛）；
        否则返回 None（由调用方按「非超管」处理，通常 403）。
        """
        row = await RbacDao.get_super_admin_identity(user_id)
        if row is None:
            return None
        return Identity(
            user_id=user_id,
            tenant_id=None,
            role_name=row["role_name"],
            tenant_is_primary=bool(row["tenant_is_primary"]),
            scopes=list(row["scopes"]),
        )

    @staticmethod
    async def assign(user_id: int, tenant_id: int, role_id: int) -> None:
        """分配/更新 用户-租户-角色（PK 冲突即更新，保证单租户内只任一角色）。"""
        await RbacDao.upsert_membership(user_id, tenant_id, role_id)
        logger.info(f"分配角色 user={user_id} tenant={tenant_id} role={role_id}")
