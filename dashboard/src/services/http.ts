/**
 * 后端请求封装
 *
 * 约定：后端统一返回 { code: 0, msg: '', data }，非 0 视为业务失败并抛错。
 * 基础地址走 VITE_API_BASE（默认空，由 vite proxy 转发到 localhost:8000）。
 * 本地 dev 后端无网关 JWT，走 dev_user_id 兜底，故默认不携带 Authorization。
 */

const BASE: string = import.meta.env.VITE_API_BASE ?? '';

export interface ApiEnvelope<T> {
  code: number;
  msg: string;
  data: T | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new Error(`请求失败：HTTP ${res.status}`);
  }
  const body = (await res.json()) as ApiEnvelope<T>;
  if (body.code !== 0) {
    throw new Error(body.msg || `业务失败 code=${body.code}`);
  }
  return body.data as T;
}

export const http = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, payload?: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(payload ?? {}) }),
  patch: <T>(path: string, payload?: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(payload ?? {}) }),
  put: <T>(path: string, payload?: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(payload ?? {}) }),
};
