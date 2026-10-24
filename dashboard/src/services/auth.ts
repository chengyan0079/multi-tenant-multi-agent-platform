/**
 * 登录鉴权（前端 Mock 版）
 *
 * 约定：
 * - 内置账号 admin / admin；无验证码、无注册、无修改密码入口。
 * - 登录成功后写入 localStorage，刷新保持登录态；后续可替换为真实后端接口。
 */

const TOKEN_KEY = 'ap_token';
const USER_KEY = 'ap_user';

export const DEFAULT_ACCOUNT = { username: 'admin', password: 'admin' };

export interface UserInfo {
  username: string;
  role: string;
}

export type LoginResult = { ok: true; user: UserInfo } | { ok: false; message: string };

export function login(username: string, password: string): LoginResult {
  if (username === DEFAULT_ACCOUNT.username && password === DEFAULT_ACCOUNT.password) {
    const user: UserInfo = { username, role: 'admin' };
    localStorage.setItem(TOKEN_KEY, `mock-token-${Date.now()}`);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    return { ok: true, user };
  }
  return { ok: false, message: '用户名或密码错误（默认 admin / admin）' };
}

export function isLogin(): boolean {
  return Boolean(localStorage.getItem(TOKEN_KEY));
}

export function getUser(): UserInfo {
  const raw = localStorage.getItem(USER_KEY);
  if (raw) {
    try {
      return JSON.parse(raw) as UserInfo;
    } catch {
      return { username: DEFAULT_ACCOUNT.username, role: 'admin' };
    }
  }
  return { username: DEFAULT_ACCOUNT.username, role: 'admin' };
}

export function logout(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}
