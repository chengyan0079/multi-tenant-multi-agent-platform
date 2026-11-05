/**
 * 登录鉴权（对接后端 POST /api/v1/auth/login）
 *
 * 约定：
 * - 身份只来自后端签发的 JWT，前端不再有 mock 账号，也不传身份头；
 * - 登录响应自带 user / 租户 / scopes / 菜单树，落地到 localStorage 供布局直接渲染；
 * - 过期时间按 expires_in 换算成本地时间戳，刷新页面时据此判断登录态。
 */
import { http, resetTrace } from './http';
import { clearToken, getToken, setToken } from './token';

const SESSION_KEY = 'ap_session';

export interface LoginUser {
  user_id: number;
  username: string;
  name?: string | null;
}

export interface CurrentTenant {
  id: number;
  name: string;
}

export interface MenuNode {
  id: number;
  name: string;
  path: string;
  icon?: string | null;
  children?: MenuNode[];
}

/** POST /auth/login 的 data 结构（与后端 LoginData 对齐）。 */
export interface LoginData {
  token: string;
  expires_in: number;
  user: LoginUser;
  is_super_admin: boolean;
  is_tenant_admin: boolean;
  current_tenant: CurrentTenant | null;
  scopes: string[];
  menus: MenuNode[];
}

/** 前端保存的会话：登录响应的裁剪版 + 过期时间戳。 */
export interface Session {
  user: LoginUser;
  isSuperAdmin: boolean;
  isTenantAdmin: boolean;
  tenant: CurrentTenant | null;
  scopes: string[];
  menus: MenuNode[];
  expiresAt: number;
}

/** 布局/页头展示用的身份摘要。 */
export interface UserInfo {
  username: string;
  name: string;
  role: string;
  tenantName: string;
}

export function login(username: string, password: string, tenantId?: number): Promise<Session> {
  return http
    .post<LoginData>('/api/v1/auth/login', {
      username,
      password,
      tenant_id: tenantId ?? null,
    })
    .then((data) => {
      const session: Session = {
        user: data.user,
        isSuperAdmin: data.is_super_admin,
        isTenantAdmin: data.is_tenant_admin,
        tenant: data.current_tenant,
        scopes: data.scopes,
        menus: data.menus,
        expiresAt: Date.now() + data.expires_in * 1000,
      };
      setToken(data.token);
      localStorage.setItem(SESSION_KEY, JSON.stringify(session));
      return session;
    });
}

export async function logout(): Promise<void> {
  // 先通知后端使 Redis 会话失效；已失效或网络异常也清本地，不阻断登出
  if (getToken()) {
    try {
      await http.post('/api/v1/auth/logout', {});
    } catch {
      // 后端会话已不存在或网络不通，忽略，继续清本地
    }
  }
  clearToken();
  localStorage.removeItem(SESSION_KEY);
  resetTrace();
}

/** 读会话：token 丢失或已过期都视为未登录，并顺手清理脏数据。 */
export function getSession(): Session | null {
  if (!getToken()) {
    return null;
  }
  const raw = localStorage.getItem(SESSION_KEY);
  if (!raw) {
    return null;
  }
  try {
    const session = JSON.parse(raw) as Session;
    if (!session.expiresAt || session.expiresAt <= Date.now()) {
      logout();
      return null;
    }
    return session;
  } catch {
    logout();
    return null;
  }
}

export function isLogin(): boolean {
  return getSession() !== null;
}

/** 当前会话是否为「租户侧」（非超管）。后端 RBAC 按角色把接口拆成 /api/v1/admin 与
 *  /api/v1/tenant 两套，前端据此选基路径：超管走 admin，租户管理员走 tenant。 */
export function isTenantContext(): boolean {
  const s = getSession();
  return s != null && !s.isSuperAdmin;
}

export function getUser(): UserInfo {
  const session = getSession();
  if (!session) {
    return { username: '', name: '', role: '', tenantName: '' };
  }
  const role = session.isSuperAdmin ? '超级管理员' : session.isTenantAdmin ? '租户管理员' : '普通用户';
  return {
    username: session.user.username,
    name: session.user.name || session.user.username,
    role,
    tenantName: session.tenant?.name ?? '',
  };
}

/** 当前会话的权限点列表（未登录/无 scope 返回空数组）。 */
export function getScopes(): string[] {
  return getSession()?.scopes ?? [];
}

/** 是否拥有某权限点（scopes 含 '*' 视为全通，与后端菜单过滤一致）。 */
export function hasScope(scope: string): boolean {
  const s = getScopes();
  return s.includes('*') || s.includes(scope);
}

/** 是否同时拥有全部给定权限点。 */
export function hasAllScopes(...scopes: string[]): boolean {
  const s = getScopes();
  return s.includes('*') || scopes.every((x) => s.includes(x));
}

/** 是否拥有任一给定权限点。 */
export function hasAnyScopes(...scopes: string[]): boolean {
  const s = getScopes();
  return s.includes('*') || scopes.some((x) => s.includes(x));
}
