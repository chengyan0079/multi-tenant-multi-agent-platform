"""RBAC：角色/权限解析服务，scope 为单一权威来源，身份由 JWT 解析后查库授权。"""

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
    """AI 业务域（权限点的资源部分）：qa / knowledge。新增业务域在此登记。"""

    QA = "qa"
    QA_FILE = "qa_file"
    QA_RESULT = "qa_result"
    QA_SESSION = "qa_session"
    # 统一咨询入口（单聊天框收口 4 个 Agent 的发起动作）
    UNIFIED = "unified"
    UNIFIED_SESSION = "unified_session"
    # 业务域分组菜单（/agent 父节点，仅用于菜单可见性）
    BUSINESS = "business"


class Agent(str, Enum):
    """基建域（权限点的资源部分）：config / agent / model，仅超管维护。"""

    CONFIG = "config"
    AGENT = "agent"
    MODEL = "model"
    TOOL = "tool"


class System(str, Enum):
    """平台域（权限点的资源部分）：audit / message / auth / user / rbac / menu / tenant / dashboard / file。"""

    AUDIT = "audit"
    MESSAGE = "message"
    USER = "user"
    MENU = "menu"
    TENANT = "tenant"
    ROLE = "role"
    RBAC = "rbac"
    DASHBOARD = "dashboard"


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
    MENU = "menu"
    REVIEW = "review"


class Scope:
    """权限点（scope）单一权威来源：``{资源}:{动作}`` 组合。

    资源取自 Business（AI 业务域）/ Agent（基建域）/ System（平台域），动作取自 Action。
    新增权限点须在 Scope 中登记，任何散落字符串字面量都会在校验时立即报错。
    """

    # ===== 业务域分组菜单（/agent 父节点）=====
    BUSINESS_MENU = f"{Business.BUSINESS.value}:{Action.MENU.value}"

    # ===== Dashboard 仪表盘：菜单可见性用 dashboard:menu，接口访问用 dashboard:view =====
    DASHBOARD_MENU = f"{System.DASHBOARD.value}:{Action.MENU.value}"
    DASHBOARD_VIEW = f"{System.DASHBOARD.value}:{Action.VIEW.value}"

    # ===== Unified 统一咨询入口 =====
    # 菜单可见性用 unified:menu（资源在前，见 scope 命名规范）；
    # 接口统一用 unified:ask 作为发起门槛（运行期再按 spec 做 agent 级启用校验）。
    UNIFIED_MENU = f"{Business.UNIFIED.value}:{Action.MENU.value}"
    UNIFIED_ASK = f"{Business.UNIFIED.value}:{Action.ASK.value}"
    # 会话管理（双入口：聊天框内列表用 unified:ask；管理页用以下三个）
    UNIFIED_SESSION_PAGE = f"{Business.UNIFIED_SESSION.value}:{Action.PAGE.value}"
    UNIFIED_SESSION_VIEW = f"{Business.UNIFIED_SESSION.value}:{Action.VIEW.value}"
    UNIFIED_SESSION_DELETE = f"{Business.UNIFIED_SESSION.value}:{Action.DELETE.value}"

    # ===== Agent 基建域（config / agent / model，仅超管） =====
    # Config 配置中心：分页列表/历史列表(page)、详情/历史详情/对比(view)、发起申请(add)、编辑/撤回(update)
    CONFIG_MENU = f"{Agent.CONFIG.value}:{Action.MENU.value}"
    CONFIG_PAGE = f"{Agent.CONFIG.value}:{Action.PAGE.value}"
    CONFIG_VIEW = f"{Agent.CONFIG.value}:{Action.VIEW.value}"
    CONFIG_ADD = f"{Agent.CONFIG.value}:{Action.ADD.value}"
    CONFIG_UPDATE = f"{Agent.CONFIG.value}:{Action.UPDATE.value}"

    # execute=执行/驳回；delete=删除申请，rollback=回滚
    CONFIG_EXECUTE = f"{Agent.CONFIG.value}:{Action.EXECUTE.value}"
    CONFIG_DELETE = f"{Agent.CONFIG.value}:{Action.DELETE.value}"
    CONFIG_ROLLBACK = f"{Agent.CONFIG.value}:{Action.ROLLBACK.value}"
    # CONFIG_LIST = f"{Agent.CONFIG.value}:{Action.LIST.value}"

    # Agent 智能体：全量列表(list)、详情(view)、租户开通策略(update)、启停(status)
    AGENT_MENU = f"{Agent.AGENT.value}:{Action.MENU.value}"
    AGENT_PAGE = f"{Agent.AGENT.value}:{Action.PAGE.value}"
    AGENT_LIST = f"{Agent.AGENT.value}:{Action.LIST.value}"
    AGENT_VIEW = f"{Agent.AGENT.value}:{Action.VIEW.value}"
    AGENT_ADD = f"{Agent.AGENT.value}:{Action.ADD.value}"
    AGENT_UPDATE = f"{Agent.AGENT.value}:{Action.UPDATE.value}"
    AGENT_DELETE = f"{Agent.AGENT.value}:{Action.DELETE.value}"
    AGENT_STATUS = f"{Agent.AGENT.value}:{Action.STATUS.value}"

    # Model 模型配置
    MODEL_MENU = f"{Agent.MODEL.value}:{Action.MENU.value}"
    MODEL_PAGE = f"{Agent.MODEL.value}:{Action.PAGE.value}"
    MODEL_VIEW = f"{Agent.MODEL.value}:{Action.VIEW.value}"
    MODEL_ADD = f"{Agent.MODEL.value}:{Action.ADD.value}"
    MODEL_UPDATE = f"{Agent.MODEL.value}:{Action.UPDATE.value}"
    MODEL_DELETE = f"{Agent.MODEL.value}:{Action.DELETE.value}"
    MODEL_STATUS = f"{Agent.MODEL.value}:{Action.STATUS.value}"

    # ===== System 平台域（audit / message / auth / user / rbac / menu / tenant / dashboard） =====
    # Audit 审计日志：只读，不提供增删改
    AUDIT_MENU = f"{System.AUDIT.value}:{Action.MENU.value}"
    AUDIT_PAGE = f"{System.AUDIT.value}:{Action.PAGE.value}"
    AUDIT_VIEW = f"{System.AUDIT.value}:{Action.VIEW.value}"

    # Message 消息管理：超管 + 租户管理员（队列 / 死信分页列表、详情 view、状态变更 status）
    MESSAGE_MENU = f"{System.MESSAGE.value}:{Action.MENU.value}"
    MESSAGE_PAGE = f"{System.MESSAGE.value}:{Action.PAGE.value}"
    MESSAGE_VIEW = f"{System.MESSAGE.value}:{Action.VIEW.value}"
    MESSAGE_STATUS = f"{System.MESSAGE.value}:{Action.STATUS.value}"

    # User 用户管理：分页列表、详情、增删改、状态变更
    USER_MENU = f"{System.USER.value}:{Action.MENU.value}"
    USER_PAGE = f"{System.USER.value}:{Action.PAGE.value}"
    USER_VIEW = f"{System.USER.value}:{Action.VIEW.value}"
    USER_ADD = f"{System.USER.value}:{Action.ADD.value}"
    USER_UPDATE = f"{System.USER.value}:{Action.UPDATE.value}"
    USER_DELETE = f"{System.USER.value}:{Action.DELETE.value}"
    USER_STATUS = f"{System.USER.value}:{Action.STATUS.value}"

    # RBAC 权限中心（父菜单入口）：仅 rbac:list 控制"权限中心"可见性
    # RBAC_LIST = f"{System.RBAC.value}:{Action.LIST.value}"
    # Role 角色管理（资源名 role，独立于 rbac）：列表/分页/新建/更新/删除
    ROLE_MENU = f"{System.ROLE.value}:{Action.MENU.value}"
    ROLE_PAGE = f"{System.ROLE.value}:{Action.PAGE.value}"
    ROLE_ADD = f"{System.ROLE.value}:{Action.ADD.value}"
    ROLE_UPDATE = f"{System.ROLE.value}:{Action.UPDATE.value}"
    ROLE_DELETE = f"{System.ROLE.value}:{Action.DELETE.value}"
    # Menu 菜单管理（仅超管；租户管理员不可维护前端导航）：分页列表、增删改、显隐
    MENU_MENU = f"{System.MENU.value}:{Action.MENU.value}"
    MENU_PAGE = f"{System.MENU.value}:{Action.PAGE.value}"
    MENU_ADD = f"{System.MENU.value}:{Action.ADD.value}"
    MENU_UPDATE = f"{System.MENU.value}:{Action.UPDATE.value}"
    MENU_DELETE = f"{System.MENU.value}:{Action.DELETE.value}"
    MENU_STATUS = f"{System.MENU.value}:{Action.STATUS.value}"
    # 权限中心父菜单入口（含 租户/用户/角色/菜单 管理，以 rbac:menu 控制可见性）
    RBAC_MENU = f"{System.RBAC.value}:{Action.MENU.value}"

    # Tenant 租户管理：分页列表、详情、增改、管理员更换、启停
    TENANT_MENU = f"{System.TENANT.value}:{Action.MENU.value}"
    TENANT_PAGE = f"{System.TENANT.value}:{Action.PAGE.value}"
    TENANT_VIEW = f"{System.TENANT.value}:{Action.VIEW.value}"
    TENANT_ADD = f"{System.TENANT.value}:{Action.ADD.value}"
    TENANT_DELETE = f"{System.TENANT.value}:{Action.DELETE.value}"
    TENANT_STATUS = f"{System.TENANT.value}:{Action.STATUS.value}"

    # Tool 工具中心
    TOOL_MENU = f"{Agent.TOOL.value}:{Action.MENU.value}"
    TOOL_PAGE = f"{Agent.TOOL.value}:{Action.PAGE.value}"
    TOOL_VIEW = f"{Agent.TOOL.value}:{Action.VIEW.value}"
    TOOL_ADD = f"{Agent.TOOL.value}:{Action.ADD.value}"
    TOOL_UPDATE = f"{Agent.TOOL.value}:{Action.UPDATE.value}"
    TOOL_DELETE = f"{Agent.TOOL.value}:{Action.DELETE.value}"
    TOOL_STATUS = f"{Agent.TOOL.value}:{Action.STATUS.value}"

    # ===== Business AI 业务域（qa / knowledge） =====
    # 问哪一类就要求哪一类的 ask 权限；page=历史列表、view=单条详情
    QA_MENU = f"{Business.QA.value}:{Action.MENU.value}"
    QA_ASK = f"{Business.QA.value}:{Action.ASK.value}"
    # 问答结果
    QA_RESULT_PAGE = f"{Business.QA_RESULT.value}:{Action.PAGE.value}"
    QA_RESULT_VIEW = f"{Business.QA_RESULT.value}:{Action.VIEW.value}"
    QA_RESULT_REVIEW = f"{Business.QA_RESULT.value}:{Action.REVIEW.value}"
    # 问答会话
    QA_SESSION_PAGE = f"{Business.QA_SESSION.value}:{Action.PAGE.value}"
    QA_SESSION_ADD = f"{Business.QA_SESSION.value}:{Action.ADD.value}"
    QA_SESSION_VIEW = f"{Business.QA_SESSION.value}:{Action.VIEW.value}"
    QA_SESSION_DELETE = f"{Business.QA_SESSION.value}:{Action.DELETE.value}"
    # 问答文件
    QA_FILE_UPLOAD = f"{Business.QA_FILE.value}:{Action.UPLOAD.value}"
    QA_FILE_DOWNLOAD = f"{Business.QA_FILE.value}:{Action.DOWNLOAD.value}"
    QA_FILE_PAGE = f"{Business.QA_FILE.value}:{Action.PAGE.value}"
    QA_FILE_VIEW = f"{Business.QA_FILE.value}:{Action.VIEW.value}"


# 所有合法权限点，供 require_scope 校验声明合法性（Scope 不再是 Enum）
# 只取大写常量名登记的值：vars(Scope) 还含 __module__ / __qualname__ / __doc__ 等
# 字符串型类元数据，若一并收进来会污染权限点清单（前端下拉出现垃圾项、校验放行脏值）。
VALID_SCOPES: frozenset[str] = frozenset(
    v for k, v in vars(Scope).items() if k.isupper() and isinstance(v, str)
)


# agent_type → 调用该 Agent 所需权限点（动态入口鉴权的单一权威来源）。
# 编排/统一聊天在运行期才决定 agent_type，无法用静态 require_scope 声明，故按此表查权限点。
SCOPE_BY_AGENT: dict[str, str] = {
    "qa": Scope.QA_ASK,
}


def scope_for_agent(agent_type: str | None) -> str | None:
    """取调用该 Agent 所需权限点；未登记类型返回 None（调用方应按拒绝处理）。"""
    return SCOPE_BY_AGENT.get(agent_type) if agent_type else None


def has_scope(scopes: list[str], required: str) -> bool:
    """是否具备权限点（精确匹配，与 require_scope 语义一致；项目不使用通配）。"""
    return required in scopes


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


@dataclass(frozen=True)
class Identity:
    """请求期身份快照：用户在某个租户内的角色名与权限点。

    超管身份以 agent_user.is_super_admin 标记为准（由 resolve_super_admin 注入，
    current.is_super_admin 下游只读布尔值，不再比 role_id / 角色名 / 租户）；
    超管没有租户上下文，tenant_id 恒为 None。
    """

    user_id: int  # 用户 id
    tenant_id: int | None  # 当前租户 id；超管为 None
    role_name: str  # 角色名
    scopes: list[str]  # 权限点集合
    is_super_admin: bool = False  # 是否平台超管

    @property
    def is_tenant_admin(self) -> bool:
        """租户管理员：tenant_admin 角色。"""
        return is_tenant_admin_role(self.role_name)


class RbacService:
    """角色/权限解析（无状态，纯查库 + 固定内置目录）。"""

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
