"""
rbac - 角色/权限解析服务（设计文档 §9.1 ③ RBAC；身份由 JWT 解析，后端只做授权）

职责：
- resolve(user_id, tenant_id)：查 agent_user_tenant → agent_role → agent_role_permission，给出
  (role_name, scopes[])。后端据此做 require_role / require_scope，不信任 token 里的角色。
- ensure_default_roles()：幂等写入固定内置角色(admin/tenant_admin)与权限点（全局，tenant 无关）。
- assign(user_id, tenant_id, role_id)：一人一租户一角色（PK 冲突即更新）。

权限点词汇（scope）：以 Scope 枚举（见下方）与 DEFAULT_ROLES 为**单一权威来源**；
格式为 ``{资源}:{动作}``，资源取自 Business（AI 业务域）/ Agent（基建域）/ System（平台域），
动作取自 Action（list/page/view/add/update/delete/upload/download/review/ask/status）。
新增权限点须在 Scope 中登记，任何散落字符串字面量都会在校验时立即报错。
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

class Business(str, Enum):
    """AI 业务域（权限点的资源部分）：qa / interview / resume / exam / knowledge。新增业务域在此登记。"""
    QA = "qa"
    INTERVIEW = "interview"
    RESUME = "resume"
    EXAM = "exam"
    KNOWLEDGE = "knowledge"


class Agent(str, Enum):
    """基建域（权限点的资源部分）：config / agent / model，仅超管维护。"""
    CONFIG = "config"
    AGENT = "agent"
    MODEL = "model"


class System(str, Enum):
    """平台域（权限点的资源部分）：audit / message / auth / user / rbac / menu / tenant / dashboard。"""
    AUDIT = "audit"
    MESSAGE = "message"
    AUTH = "auth"
    USER = "user"
    RBAC = "rbac"
    MENU = "menu"
    TENANT = "tenant"
    DASHBOARD = "dashboard"
    FILE = "file"


class Action(str, Enum):
    """权限动词（权限点的动作部分），按业务语义统一整合。

    - list：非分页列表查询（整表/全量返回，无 page/page_size 切片）；
    - page：分页列表查询（带 page/page_size 切片）；
    - view：单条详情查询（按 id 取一条）；
    - add：新增；update：更改；delete：删除；
    - upload：上传；download：下载；review：复核（审批流）；
    - ask：询问（AI 业务域发起对话）；status：状态变更（启停 / 显隐）。
    """
    ASK = "ask"
    LIST = "list"
    PAGE = "page"
    VIEW = "view"
    UPDATE = "update"
    ADD = "add"
    DELETE = "delete"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    STATUS = "status"
    ROLLBACK = "rollback"
    EXECUTE = "execute"


class Scope:
    """权限点（scope）单一权威来源：``{资源}:{动作}`` 组合。

    资源取自 Business（AI 业务域）/ Agent（基建域）/ System（平台域），动作取自 Action。
    新增权限点须在 Scope 中登记，任何散落字符串字面量都会在校验时立即报错。
    """
    # ===== Dashboard 仪表盘（超管看全平台，租户管理员看本租户） =====
    DASHBOARD_VIEW = f"{System.DASHBOARD.value}:{Action.VIEW.value}"

    # ===== Agent 基建域（config / agent / model，仅超管） =====
    # Config 配置中心：分页列表/历史列表(page)、详情/历史详情/对比(view)、发起申请(add)、编辑/撤回(update)
    CONFIG_PAGE = f"{Agent.CONFIG.value}:{Action.PAGE.value}"
    CONFIG_VIEW = f"{Agent.CONFIG.value}:{Action.VIEW.value}"
    CONFIG_ADD = f"{Agent.CONFIG.value}:{Action.ADD.value}"
    CONFIG_UPDATE = f"{Agent.CONFIG.value}:{Action.UPDATE.value}"
    # execute=执行/驳回；delete=删除申请，rollback=回滚
    CONFIG_EXECUTE = f"{Agent.CONFIG.value}:{Action.EXECUTE.value}"
    CONFIG_DELETE = f"{Agent.CONFIG.value}:{Action.DELETE.value}"
    CONFIG_ROLLBACK = f"{Agent.CONFIG.value}:{Action.ROLLBACK.value}"
    # Agent 智能体：全量列表(list)、详情(view)、租户开通策略(update)、启停(status)
    AGENT_PAGE = f"{Agent.AGENT.value}:{Action.PAGE.value}"
    AGENT_LIST = f"{Agent.AGENT.value}:{Action.LIST.value}"
    AGENT_VIEW = f"{Agent.AGENT.value}:{Action.VIEW.value}"
    AGENT_ADD = f"{Agent.AGENT.value}:{Action.ADD.value}"
    AGENT_UPDATE = f"{Agent.AGENT.value}:{Action.UPDATE.value}"
    AGENT_DELETE = f"{Agent.AGENT.value}:{Action.DELETE.value}"
    AGENT_STATUS = f"{Agent.AGENT.value}:{Action.STATUS.value}"
    # Model 模型配置
    MODEL_PAGE = f"{Agent.MODEL.value}:{Action.PAGE.value}"
    MODEL_VIEW = f"{Agent.MODEL.value}:{Action.VIEW.value}"
    MODEL_ADD = f"{Agent.MODEL.value}:{Action.ADD.value}"
    MODEL_UPDATE = f"{Agent.MODEL.value}:{Action.UPDATE.value}"
    MODEL_DELETE = f"{Agent.MODEL.value}:{Action.DELETE.value}"
    MODEL_STATUS = f"{Agent.MODEL.value}:{Action.STATUS.value}"

    # ===== System 平台域（audit / message / auth / user / rbac / menu / tenant / dashboard） =====
    # Audit 审计日志：只读，不提供增删改
    AUDIT_PAGE = f"{System.AUDIT.value}:{Action.PAGE.value}"
    AUDIT_VIEW = f"{System.AUDIT.value}:{Action.VIEW.value}"
    # Message 消息管理：超管 + 租户管理员（队列 / 死信分页列表、详情 view、状态变更 status）
    MESSAGE_PAGE = f"{System.MESSAGE.value}:{Action.PAGE.value}"
    MESSAGE_VIEW = f"{System.MESSAGE.value}:{Action.VIEW.value}"
    MESSAGE_STATUS = f"{System.MESSAGE.value}:{Action.STATUS.value}"
    # Auth 登录鉴权：菜单 / 个人信息（自端点仅依赖登录态，这里登记备用）
    AUTH_PAGE = f"{System.AUTH.value}:{Action.PAGE.value}"
    AUTH_UPDATE = f"{System.AUTH.value}:{Action.UPDATE.value}"
    # User 用户管理：分页列表、详情、增删改、状态变更
    USER_PAGE = f"{System.USER.value}:{Action.PAGE.value}"
    USER_VIEW = f"{System.USER.value}:{Action.VIEW.value}"
    USER_ADD = f"{System.USER.value}:{Action.ADD.value}"
    USER_UPDATE = f"{System.USER.value}:{Action.UPDATE.value}"
    USER_DELETE = f"{System.USER.value}:{Action.DELETE.value}"
    USER_STATUS = f"{System.USER.value}:{Action.STATUS.value}"
    # RBAC 用户与角色管理：分页列表、新建、覆盖权限、删除
    RBAC_PAGE = f"{System.RBAC.value}:{Action.PAGE.value}"
    RBAC_ADD = f"{System.RBAC.value}:{Action.ADD.value}"
    RBAC_UPDATE = f"{System.RBAC.value}:{Action.UPDATE.value}"
    RBAC_DELETE = f"{System.RBAC.value}:{Action.DELETE.value}"
    # Menu 菜单管理（仅超管；租户管理员不可维护前端导航）：分页列表、增删改、显隐
    MENU_PAGE = f"{System.MENU.value}:{Action.PAGE.value}"
    MENU_ADD = f"{System.MENU.value}:{Action.ADD.value}"
    MENU_UPDATE = f"{System.MENU.value}:{Action.UPDATE.value}"
    MENU_DELETE = f"{System.MENU.value}:{Action.DELETE.value}"
    MENU_STATUS = f"{System.MENU.value}:{Action.STATUS.value}"
    # Tenant 租户管理：分页列表、详情、增改、管理员更换、启停
    TENANT_PAGE = f"{System.TENANT.value}:{Action.PAGE.value}"
    TENANT_VIEW = f"{System.TENANT.value}:{Action.VIEW.value}"
    TENANT_ADD = f"{System.TENANT.value}:{Action.ADD.value}"
    TENANT_UPDATE = f"{System.TENANT.value}:{Action.UPDATE.value}"
    TENANT_DELETE = f"{System.TENANT.value}:{Action.DELETE.value}"
    TENANT_STATUS = f"{System.TENANT.value}:{Action.STATUS.value}"
    # 文件上传下载
    FILE_UPLOAD = f"{System.FILE.value}:{Action.UPLOAD.value}"
    FILE_DOWNLOAD = f"{System.FILE.value}:{Action.DOWNLOAD.value}"
    FILE_PAGE = f"{System.FILE.value}:{Action.PAGE.value}"
    FILE_VIEW = f"{System.FILE.value}:{Action.VIEW.value}"

    # ===== Business AI 业务域（qa / interview / resume / exam / knowledge） =====
    # 问哪一类就要求哪一类的 ask 权限；page=历史列表、view=单条详情
    QA_ASK = f"{Business.QA.value}:{Action.ASK.value}"
    QA_PAGE = f"{Business.QA.value}:{Action.PAGE.value}"
    QA_VIEW = f"{Business.QA.value}:{Action.VIEW.value}"
    INTERVIEW_ASK = f"{Business.INTERVIEW.value}:{Action.ASK.value}"
    INTERVIEW_PAGE = f"{Business.INTERVIEW.value}:{Action.PAGE.value}"
    INTERVIEW_VIEW = f"{Business.INTERVIEW.value}:{Action.VIEW.value}"
    RESUME_ASK = f"{Business.RESUME.value}:{Action.ASK.value}"
    RESUME_UPLOAD = f"{Business.RESUME.value}:{Action.UPLOAD.value}"
    RESUME_PAGE = f"{Business.RESUME.value}:{Action.PAGE.value}"
    RESUME_VIEW = f"{Business.RESUME.value}:{Action.VIEW.value}"
    EXAM_ASK = f"{Business.EXAM.value}:{Action.ASK.value}"
    EXAM_PAGE = f"{Business.EXAM.value}:{Action.PAGE.value}"
    EXAM_ADD = f"{Business.EXAM.value}:{Action.ADD.value}"
    EXAM_UPDATE = f"{Business.EXAM.value}:{Action.UPDATE.value}"
    EXAM_VIEW = f"{Business.EXAM.value}:{Action.VIEW.value}"
    KNOWLEDGE_ASK = f"{Business.KNOWLEDGE.value}:{Action.ASK.value}"
    KNOWLEDGE_PAGE = f"{Business.KNOWLEDGE.value}:{Action.PAGE.value}"
    KNOWLEDGE_UPLOAD = f"{Business.KNOWLEDGE.value}:{Action.UPLOAD.value}"
    KNOWLEDGE_DOWNLOAD = f"{Business.KNOWLEDGE.value}:{Action.DOWNLOAD.value}"
    KNOWLEDGE_VIEW = f"{Business.KNOWLEDGE.value}:{Action.VIEW.value}"


# 所有合法权限点，供 require_scope 校验声明合法性（Scope 不再是 Enum）
# 只取大写常量名登记的值：vars(Scope) 还含 __module__ / __qualname__ / __doc__ 等
# 字符串型类元数据，若一并收进来会污染权限点清单（前端下拉出现垃圾项、校验放行脏值）。
VALID_SCOPES: frozenset[str] = frozenset(
    v for k, v in vars(Scope).items() if k.isupper() and isinstance(v, str)
)


class RoleName(str, Enum):
    """固定角色名（身份判定的依据）。

    只有超管（admin）与租户管理员（tenant_admin）是平台固定角色，代码据此做
    超管/租管判定；其余角色（student / teacher 等）完全由数据库驱动，不在代码枚举。
    超管判定只看 `agent_user.is_super_admin`、不看角色名与租户；角色判定只看角色名，
    不看 `role_id` 数字：role_id 是入库用的代理业务键，库表重建、迁移、多环境种子
    都可能不同，写死在代码里必然出错。
    """

    ADMIN = "admin"
    TENANT_ADMIN = "tenant_admin"


def is_tenant_admin_role(role_name: str | None) -> bool:
    """是否为租户管理员：只认角色名 tenant_admin。"""
    return role_name == RoleName.TENANT_ADMIN.value


# # 固定内置角色目录：role_id(int 业务键) → (可读名 name, 权限点 scopes[])。
# # 与 scripts/schema.sql 的 RBAC 默认数据保持一致；角色判断统一以 name 为准。
# # 注意：本常量仅作为 ensure_default_roles() 的「种子源」写入数据库，
# # 请求期授权解析一律以 agent_role_permission 表为准，本常量不参与任何兜底。
# # scope 使用 Scope 枚举成员，确保任何拼写错误在加载期即暴露。
# # 仅 admin 一个固定角色在此登记；tenant_admin 等其余角色由前端创建，运行期全由数据库驱动。
# DEFAULT_ROLES: dict[int, tuple[str, list[Scope]]] = {
#     1: ("admin", [
#         # Dashboard 仪表盘（超管看全平台，租户管理员看本租户）
#         Scope.DASHBOARD_VIEW,
#         # Agent 基建域
#         Scope.CONFIG_PAGE, Scope.CONFIG_VIEW, Scope.CONFIG_ADD, Scope.CONFIG_UPDATE, Scope.CONFIG_ROLLBACK,
#         Scope.CONFIG_EXECUTE, Scope.CONFIG_DELETE,
#         Scope.AGENT_PAGE, Scope.AGENT_LIST, Scope.AGENT_VIEW, Scope.AGENT_ADD, Scope.AGENT_UPDATE, Scope.AGENT_DELETE, Scope.AGENT_STATUS,
#         Scope.MODEL_PAGE, Scope.MODEL_VIEW, Scope.MODEL_ADD, Scope.MODEL_UPDATE, Scope.MODEL_DELETE, Scope.MODEL_STATUS,
#         # System 平台域
#         Scope.AUTH_PAGE, Scope.AUTH_UPDATE,
#         Scope.RBAC_PAGE, Scope.RBAC_ADD, Scope.RBAC_UPDATE, Scope.RBAC_DELETE,
#         Scope.USER_PAGE, Scope.USER_VIEW, Scope.USER_ADD, Scope.USER_UPDATE, Scope.USER_DELETE, Scope.USER_STATUS,
#         Scope.TENANT_PAGE, Scope.TENANT_VIEW, Scope.TENANT_ADD, Scope.TENANT_UPDATE, Scope.TENANT_DELETE, Scope.TENANT_STATUS,
#         Scope.AUDIT_PAGE, Scope.AUDIT_VIEW,
#         Scope.MESSAGE_PAGE, Scope.MESSAGE_VIEW, Scope.MESSAGE_STATUS,
#         Scope.MENU_PAGE, Scope.MENU_ADD, Scope.MENU_UPDATE, Scope.MENU_DELETE, Scope.MENU_STATUS,
#     ]),
# }


@dataclass(frozen=True)
class Identity:
    """请求期身份快照：用户在某个租户内的角色名与权限点。

    超管身份以 agent_user.is_super_admin 标记为准（由 resolve_super_admin 注入，
    current.is_super_admin 下游只读布尔值，不再比 role_id / 角色名 / 租户）；
    超管没有租户上下文，tenant_id 恒为 None。
    """

    user_id: int
    tenant_id: int | None
    role_name: str
    scopes: list[str]
    is_super_admin: bool = False

    @property
    def is_tenant_admin(self) -> bool:
        """租户管理员：tenant_admin 角色。"""
        return is_tenant_admin_role(self.role_name)


class RbacService:
    """角色/权限解析（无状态，纯查库 + 固定内置目录）。"""

    # @staticmethod
    # async def ensure_default_roles() -> None:
    #     """幂等写入固定内置角色与权限点（全局，tenant 无关）。
    #
    #     注意：启动**不再**自动调用本方法（已移除 RbacSeedManager）。超管权限改由
    #     schema.sql 的 SEED_RBAC 在建库时静态注入，保证存在且齐全；后续改动走手动
    #     SQL 或前端 RBAC 维护接口。本方法仅保留为手动 seed / 单测入口。
    #     启动期没有请求上下文，审计列显式记到系统身份占位（SYSTEM_USER_ID，非真实超管 id）。
    #     """
    #     roles = [
    #         (role_id, name, f"内置角色 {name}")
    #         for role_id, (name, _) in DEFAULT_ROLES.items()
    #     ]
    #     permissions = [
    #         (role_id, scope)
    #         for role_id, (_, scopes) in DEFAULT_ROLES.items()
    #         for scope in scopes
    #     ]
    #     new_roles, new_perms = await RbacDao.ensure_roles_and_permissions(
    #         roles, permissions, user_id=SYSTEM_USER_ID
    #     )
    #     logger.info(f"固定内置角色与权限点已确保（新增角色 {new_roles}、权限点 {new_perms}）")

    @staticmethod
    async def resolve_identity(user_id: int, tenant_id: int) -> Optional[Identity]:
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
            scopes=row["scopes"],
            is_super_admin=False,
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
        """超管分支解析：token 不含 tenant_id，仅按 agent_user.is_super_admin 判定（§4.2 / §5.2）。

        命中返回 tenant_id=None（超管完全不挂租户）/ is_super_admin=True /
        scopes=admin 角色的具体权限点（菜单由 scope 驱动，超管自然只看到有权限的基建菜单）；否则 None。
        """
        row = await RbacDao.get_super_admin_identity(user_id)
        if row is None:
            return None
        return Identity(
            user_id=user_id,
            tenant_id=None,
            role_name=RoleName.ADMIN.value,
            scopes=list(row["scopes"]),
            is_super_admin=True,
        )

    @staticmethod
    async def assign(user_id: int, tenant_id: int, role_id: int) -> None:
        """分配/更新 用户-租户-角色（PK 冲突即更新，保证单租户内只任一角色）。"""
        await RbacDao.upsert_membership(user_id, tenant_id, role_id)
        logger.info(f"分配角色 user={user_id} tenant={tenant_id} role={role_id}")
