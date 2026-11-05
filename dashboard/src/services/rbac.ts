import { http } from './http';
import { isTenantContext } from './auth';

export interface UserItem {
  id: number;
  username: string;
  name: string;
  tenant_id: number;
  create_at?: string;
  updated_at?: string;
}

export interface TenantItem {
  id: number;
  name: string;
  enabled: boolean;
  manager_username: string | null;
  user_count: number;
  create_at?: string;
  updated_at?: string;
}

export interface RoleItem {
  role_id: number;
  name: string;
  description: string;
  scopes: string[];
}

export interface MenuNode {
  id: number;
  name: string;
  path: string;
  icon?: string;
  parent_id: number;
  sort_order: number;
  visible: boolean;
  scope?: string | null;
  children?: MenuNode[];
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') sp.set(k, String(v));
  });
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export async function listUsers(params: {
  page?: number;
  page_size?: number;
  tenant_id?: number;
  username?: string;
  created_from?: string;
  created_to?: string;
}) {
  // 超管走 /admin/users（可跨租户）；租户管理员走 /tenant/users（强制本租户，不接受 tenant_id）
  if (isTenantContext()) {
    const { page, page_size, username, created_from, created_to } = params;
    return http.get<Paged<UserItem>>(`/api/v1/tenant/users${qs({ page, page_size, username, created_from, created_to })}`);
  }
  return http.get<Paged<UserItem>>(`/api/v1/admin/users${qs(params)}`);
}

export async function listTenants(params: {
  page?: number;
  page_size?: number;
  name?: string;
  created_from?: string;
  created_to?: string;
}) {
  return http.get<Paged<TenantItem>>(`/api/v1/admin/tenants${qs(params)}`);
}

export async function listRoles(page = 1, pageSize = 20) {
  return http.get<Paged<RoleItem>>(`/api/v1/admin/roles${qs({ page, page_size: pageSize })}`);
}

export async function createRole(payload: { name: string; description?: string; scopes: string[] }) {
  return http.post(`/api/v1/admin/roles`, payload);
}

export async function deleteRole(roleId: number) {
  return http.delete(`/api/v1/admin/roles/${roleId}`);
}

export async function listMenus(page = 1, pageSize = 50) {
  return http.get<Paged<MenuNode>>(`/api/v1/admin/menus${qs({ page, page_size: pageSize })}`);
}

export async function createMenu(payload: {
  name: string;
  path: string;
  icon?: string;
  parent_id: number;
  sort_order?: number;
  visible?: boolean;
  scope?: string | null;
}) {
  return http.post(`/api/v1/admin/menus`, payload);
}

export async function updateMenu(
  id: number,
  payload: {
    name: string;
    path: string;
    icon?: string;
    parent_id: number;
    sort_order?: number;
    visible?: boolean;
    scope?: string | null;
  },
) {
  return http.put(`/api/v1/admin/menus/${id}`, payload);
}

export async function deleteMenu(id: number) {
  return http.delete(`/api/v1/admin/menus/${id}`);
}

export async function changeUserRole(userId: number, tenantId: number, role: string) {
  // 超管侧带租户；租户管理员侧角色仅限本租户，请求体只传 role
  if (isTenantContext()) {
    return http.put(`/api/v1/tenant/users/${userId}/role`, { role });
  }
  return http.put(`/api/v1/admin/rbac/users/${userId}/role`, { tenant_id: tenantId, role });
}

/** 新建租户并创建主租户用户（后端原子操作：建租户 + 建主用户 + 授权 tenant_admin）。 */
export async function createTenant(payload: {
  name: string;
  manager: { username: string; name?: string; password: string };
}) {
  return http.post<{ tenant_id: number; user_id: number }>('/api/v1/admin/tenants', payload);
}

/** 租户内新建用户（仅主租户/租户管理员，走 /tenant/users）。 */
export async function createTenantUser(payload: {
  username: string;
  name?: string;
  password: string;
  role: string;
}) {
  return http.post('/api/v1/tenant/users', payload);
}

/** 本租户可分配角色（含 student/teacher 等普通角色，由数据库返回，非前端硬编码）。 */
export async function listAssignableRoles() {
  return http.get<string[]>(`/api/v1/tenant/roles`);
}

/** 租户内解绑用户（仅主租户/租户管理员）。 */
export async function deleteTenantUser(userId: number) {
  return http.delete(`/api/v1/tenant/users/${userId}`);
}

/** 租户详情（含管理员、用户数、时间）。 */
export async function getTenant(tenantId: number) {
  return http.get<TenantItem & { manager_username?: string | null; user_count?: number; create_at?: string; updated_at?: string }>(
    `/api/v1/admin/tenants/${tenantId}`,
  );
}

/** 用户详情（超管；响应已剥 password，含 enabled）。 */
export async function getUser(userId: number) {
  if (isTenantContext()) {
    return http.get<UserItem & { enabled?: boolean }>(`/api/v1/tenant/users/${userId}`);
  }
  return http.get<UserItem & { enabled?: boolean }>(`/api/v1/admin/users/${userId}`);
}

/** 改角色名称/说明（权限点走 updateRolePermissions） */
export async function updateRole(roleId: number, payload: { name: string; description?: string }) {
  return http.put<{ role_id: number; name: string; description: string | null }>(
    `/api/v1/admin/roles/${roleId}`,
    payload,
  );
}

/** 覆盖角色权限点（全量列表，后端先清空再写，并会校验权限点是否合法） */
export async function updateRolePermissions(roleId: number, scopes: string[]) {
  return http.put<{ role_id: number; scopes: string[] }>(
    `/api/v1/admin/roles/${roleId}/permissions`,
    { scopes },
  );
}

/** 菜单显隐（status 端点）。 */
export async function setMenuStatus(id: number, visible: boolean) {
  return http.patch(`/api/v1/admin/menus/${id}/status`, { visible });
}

/** 租户启停（status 端点）。 */
export async function setTenantStatus(tenantId: number, enabled: boolean) {
  return http.patch(`/api/v1/admin/tenants/${tenantId}/status`, { enabled });
}

/** 删除租户（超管，tenant:delete）。 */
export async function deleteTenant(tenantId: number) {
  return http.delete(`/api/v1/admin/tenants/${tenantId}`);
}

/**
 * 权限点目录（经 GET /admin/scopes 拉取后端 Scope 全量）。
 * @deprecated 仅作历史参考，前端下拉已改由 listScopes() 动态加载。
 */
export const SCOPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'qa:ask', label: 'qa:ask（问答）' },
  { value: 'qa:page', label: 'qa:page（问答记录查询）' },
  { value: 'interview:ask', label: 'interview:ask（模拟面试）' },
  { value: 'interview:page', label: 'interview:page（面试记录查询）' },
  { value: 'resume:ask', label: 'resume:ask（简历问答）' },
  { value: 'resume:upload', label: 'resume:upload（简历上传）' },
  { value: 'resume:page', label: 'resume:page（简历查询）' },
  { value: 'resume:view', label: 'resume:view（评审查看）' },
  { value: 'resume:delete', label: 'resume:delete（评审删除）' },
  { value: 'resume:menu', label: 'resume:menu（简历评审菜单）' },
  { value: 'exam:ask', label: 'exam:ask（试卷问答）' },
  { value: 'exam:page', label: 'exam:page（试卷查询）' },
  { value: 'exam:add', label: 'exam:add（出卷）' },
  { value: 'exam:update', label: 'exam:update（改卷）' },
  { value: 'knowledge:ask', label: 'knowledge:ask（知识库问答）' },
  { value: 'knowledge:page', label: 'knowledge:page（知识库查询）' },
  { value: 'knowledge:upload', label: 'knowledge:upload（知识库上传）' },
  { value: 'knowledge:download', label: 'knowledge:download（知识库下载）' },
  { value: 'config:page', label: 'config:page（配置查询）' },
  { value: 'config:update', label: 'config:update（配置写入）' },
  { value: 'config:review', label: 'config:review（配置复核）' },
  { value: 'config:add', label: 'config:add（配置新增）' },
  { value: 'config:delete', label: 'config:delete（配置删除）' },
  { value: 'audit:page', label: 'audit:page（审计查询）' },
  { value: 'message:page', label: 'message:page（消息管理查看）' },
  { value: 'agent:page', label: 'agent:page（智能体查询）' },
  { value: 'agent:update', label: 'agent:update（智能体写入）' },
  { value: 'agent:add', label: 'agent:add（智能体新建）' },
  { value: 'agent:delete', label: 'agent:delete（智能体删除）' },
  { value: 'model:page', label: 'model:page（模型查询）' },
  { value: 'model:update', label: 'model:update（模型写入）' },
  { value: 'model:add', label: 'model:add（模型新增）' },
  { value: 'model:delete', label: 'model:delete（模型删除）' },
  { value: 'auth:login', label: 'auth:login（登录）' },
  { value: 'auth:page', label: 'auth:page（身份查询）' },
  { value: 'auth:update', label: 'auth:update（身份写入）' },
  { value: 'user:menu', label: 'user:menu（用户管理菜单）' },
  { value: 'user:page', label: 'user:page（用户查询）' },
  { value: 'user:update', label: 'user:update（用户写入）' },
  { value: 'user:add', label: 'user:add（用户新建）' },
  { value: 'user:delete', label: 'user:delete（用户删除）' },
  { value: 'rbac:menu', label: 'rbac:menu（权限中心菜单）' },
  { value: 'role:menu', label: 'role:menu（角色管理菜单）' },
  { value: 'role:page', label: 'role:page（角色查询）' },
  { value: 'role:add', label: 'role:add（角色新建）' },
  { value: 'role:update', label: 'role:update（角色写入/权限）' },
  { value: 'role:delete', label: 'role:delete（角色删除）' },
  { value: 'tenant:menu', label: 'tenant:menu（租户管理菜单）' },
  { value: 'tenant:page', label: 'tenant:page（租户查询）' },
  { value: 'tenant:update', label: 'tenant:update（租户写入）' },
  { value: 'tenant:add', label: 'tenant:add（租户新建）' },
  { value: 'tenant:delete', label: 'tenant:delete（租户删除）' },
  { value: 'agent:status', label: 'agent:status（智能体启停）' },
  { value: 'model:status', label: 'model:status（模型启停）' },
  { value: 'tenant:status', label: 'tenant:status（租户启停）' },
  { value: 'menu:status', label: 'menu:status（菜单显隐）' },
  { value: 'menu:list', label: 'menu:list（菜单管理查询）' },
  { value: 'menu:page', label: 'menu:page（菜单管理分页）' },
  { value: 'dashboard:menu', label: 'dashboard:menu（监控概览菜单）' },
  { value: 'qa:menu', label: 'qa:menu（会话运行/咨询问答菜单）' },
  { value: 'agent:menu', label: 'agent:menu（智能体/工具菜单）' },
  { value: 'model:menu', label: 'model:menu（模型配置菜单）' },
  { value: 'config:menu', label: 'config:menu（配置中心菜单）' },
  { value: 'audit:menu', label: 'audit:menu（审计日志菜单）' },
  { value: 'message:menu', label: 'message:menu（消息管理菜单）' },
  { value: 'file:menu', label: 'file:menu（文件管理菜单）' },
  { value: 'menu:menu', label: 'menu:menu（菜单管理菜单）' },
];

/** 全量权限点：直接取后端 backend/security/rbac.py 的 Scope，前端无需硬编码同步。 */
export async function listScopes(): Promise<string[]> {
  const r = await http.get<{ items: string[] }>('/api/v1/admin/scopes');
  return r.items ?? [];
}
