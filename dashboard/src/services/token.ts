/**
 * token 存取（单一职责，避免 http.ts 与 auth.ts 相互 import）
 *
 * 只负责把登录拿到的 JWT 放进 localStorage 并读出来；
 * 判断登录态、过期清理等业务语义留在 services/auth.ts。
 */

const TOKEN_KEY = 'ap_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}
