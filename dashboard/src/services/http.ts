/**
 * 后端请求封装
 *
 * 约定：
 * - 后端统一返回 { code: 0, msg: '', data }，code 非 0 视为业务失败；
 * - 已登录时自动带 `Authorization: Bearer <JWT>`（身份只来自 token，不传任何身份头）；
 * - 401 统一清 token 并跳登录页，业务代码不必各自处理登录过期；
 * - 后端错误体同样是信封结构，故非 2xx 也先解析 body，把 msg 透给调用方。
 */
import { clearToken, getToken } from './token';

const BASE: string = import.meta.env.VITE_API_BASE ?? '';

export interface ApiEnvelope<T> {
  code: number;
  msg: string;
  data: T | null;
}

/** 统一错误类型：调用方可用 instanceof 判断，也可直接读 message 展示。 */
export class ApiError extends Error {
  readonly code: number;
  readonly status: number;

  constructor(message: string, code: number, status: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

function toLogin(): void {
  clearToken();
  if (window.location.pathname !== '/login') {
    window.location.replace('/login');
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set('Content-Type', 'application/json');
  const token = getToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError('网络异常，请确认后端服务已启动', -1, 0);
  }

  const isJson = (res.headers.get('content-type') ?? '').includes('application/json');
  const body = isJson ? ((await res.json()) as ApiEnvelope<T>) : null;

  if (res.status === 401) {
    toLogin();
    throw new ApiError(body?.msg || '登录已过期，请重新登录', body?.code ?? 401, 401);
  }
  if (!res.ok) {
    throw new ApiError(body?.msg || `请求失败：HTTP ${res.status}`, body?.code ?? res.status, res.status);
  }
  if (!body) {
    throw new ApiError('响应格式异常：不是 JSON 信封', -1, res.status);
  }
  if (body.code !== 0) {
    throw new ApiError(body.msg || `业务失败 code=${body.code}`, body.code, res.status);
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
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};
