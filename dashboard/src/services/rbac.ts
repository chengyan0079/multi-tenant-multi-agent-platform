import { http } from './http';

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
  is_primary: boolean;
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

export async function listRoles() {
  return http.get<Paged<RoleItem>>(`/api/v1/admin/roles`);
}

export async function createRole(payload: { name: string; description?: string; scopes: string[] }) {
  return http.post(`/api/v1/admin/roles`, payload);
}

export async function deleteRole(roleId: number) {
  return http.delete(`/api/v1/admin/roles/${roleId}`);
}

export async function listMenus() {
  return http.get<{ items: MenuNode[]; total: number }>(`/api/v1/admin/menus`);
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
  return http.put(`/api/v1/admin/rbac/users/${userId}/role`, { tenant_id: tenantId, role });
}

export async function updateTenant(tenantId: number, payload: { name?: string; enabled?: boolean }) {
  return http.put(`/api/v1/admin/tenants/${tenantId}`, payload);
}

export async function setTenantManager(tenantId: number, username: string, password?: string) {
  return http.put(`/api/v1/admin/tenants/${tenantId}/manager`, { username, password });
}

/** 新建租户：is_primary 由后端固定为 false，不接受入参 */
export async function createTenant(name: string) {
  return http.post<{ id: number }>('/api/v1/admin/tenants', { name });
}

/** 覆盖角色权限点（全量列表，后端先清空再写，并会校验权限点是否合法） */
export async function updateRolePermissions(roleId: number, scopes: string[]) {
  return http.put<{ role_id: number; scopes: string[] }>(
    `/api/v1/admin/roles/${roleId}/permissions`,
    { scopes },
  );
}

/**
 * 权限点目录：与后端 backend/security/rbac.py 的 Scope 枚举一一对应。
 * 后端对未知权限点直接报错，所以这里只放枚举里有的值，不要临时手输。
 */
export const SCOPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'qa:ask', label: 'qa:ask（问答）' },
  { value: 'qa:read', label: 'qa:read（问答记录读取）' },
  { value: 'interview:ask', label: 'interview:ask（模拟面试）' },
  { value: 'interview:read', label: 'interview:read（面试记录读取）' },
  { value: 'resume:ask', label: 'resume:ask（简历问答）' },
  { value: 'resume:upload', label: 'resume:upload（简历上传）' },
  { value: 'resume:read', label: 'resume:read（简历读取）' },
  { value: 'exam:ask', label: 'exam:ask（试卷问答）' },
  { value: 'exam:read', label: 'exam:read（试卷读取）' },
  { value: 'exam:create', label: 'exam:create（出卷）' },
  { value: 'exam:update', label: 'exam:update（改卷）' },
  { value: 'knowledge:ask', label: 'knowledge:ask（知识库问答）' },
  { value: 'knowledge:read', label: 'knowledge:read（知识库读取）' },
  { value: 'knowledge:upload', label: 'knowledge:upload（知识库上传）' },
  { value: 'knowledge:download', label: 'knowledge:download（知识库下载）' },
  { value: 'config:read', label: 'config:read（配置读取）' },
  { value: 'config:write', label: 'config:write（配置写入）' },
  { value: 'config:review', label: 'config:review（配置复核）' },
  { value: 'config:create', label: 'config:create（配置新增）' },
  { value: 'config:update', label: 'config:update（配置修改）' },
  { value: 'config:delete', label: 'config:delete（配置删除）' },
  { value: 'audit:read', label: 'audit:read（审计读取）' },
  { value: 'agent:read', label: 'agent:read（智能体读取）' },
  { value: 'agent:write', label: 'agent:write（智能体写入）' },
  { value: 'agent:create', label: 'agent:create（智能体新建）' },
  { value: 'agent:delete', label: 'agent:delete（智能体删除）' },
  { value: 'model:read', label: 'model:read（模型读取）' },
  { value: 'model:write', label: 'model:write（模型写入）' },
  { value: 'model:create', label: 'model:create（模型新增）' },
  { value: 'model:update', label: 'model:update（模型修改）' },
  { value: 'model:delete', label: 'model:delete（模型删除）' },
  { value: 'auth:login', label: 'auth:login（登录）' },
  { value: 'auth:read', label: 'auth:read（身份读取）' },
  { value: 'auth:write', label: 'auth:write（身份写入）' },
  { value: 'user:read', label: 'user:read（用户读取）' },
  { value: 'user:write', label: 'user:write（用户写入）' },
  { value: 'user:create', label: 'user:create（用户新建）' },
  { value: 'user:delete', label: 'user:delete（用户删除）' },
  { value: 'rbac:read', label: 'rbac:read（角色读取）' },
  { value: 'rbac:write', label: 'rbac:write（角色写入）' },
  { value: 'tenant:read', label: 'tenant:read（租户读取）' },
  { value: 'tenant:write', label: 'tenant:write（租户写入）' },
  { value: 'tenant:create', label: 'tenant:create（租户新建）' },
  { value: 'tenant:delete', label: 'tenant:delete（租户删除）' },
];
