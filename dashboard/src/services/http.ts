/**
 * 后端请求封装
 *
 * 约定：
 * - 后端统一返回 { code: 0, msg: '', data }，code 非 0 视为业务失败；
 * - 已登录时自动带 `Authorization: Bearer <JWT>`（身份只来自 token，不传任何身份头）；
 * - 所有请求自动带 `X-Trace-Id`（前端生成并贯穿整站会话，与后端强制传播规则配合：
 *   非登录接口缺失 X-Trace-Id 会被后端拒绝）；登录与后续请求共享同一 trace，便于串联；
 * - 401 统一清 token 并跳登录页，业务代码不必各自处理登录过期；
 * - 后端错误体同样是信封结构，故非 2xx 也先解析 body，把 msg 透给调用方。
 */
import { clearToken, getToken } from './token';

const BASE: string = import.meta.env.VITE_API_BASE ?? '';

/** 对外暴露的基础地址，供上传/下载这类非 JSON 请求直接拼接。 */
export const API_BASE = BASE;

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

/** SSE / 裸 fetch 等非 http 封装路径复用同一套 401 处理（清 token + 跳登录页）。 */
export function handleUnauthorized(): void {
  toLogin();
}

/** 全链路 trace_id：贯穿整个前端会话（页面生命周期），首次请求时生成并固定。
 * 后端 TraceIdMiddleware 强制要求非登录接口携带 X-Trace-Id（缺失即 400），且不重新生成；
 * 这里前端统一生成并贯穿，使登录请求与后续数据请求共享同一 trace，便于排障串联。 */
function newTrace(): string {
  let u: string;
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    u = crypto.randomUUID();
  } else {
    u = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'.replace(/x/g, () =>
      ((Math.random() * 16) | 0).toString(16),
    );
  }
  return u.replace(/-/g, '');
}

let sessionTrace: string | null = null;

function ensureTrace(): string {
  if (!sessionTrace) sessionTrace = newTrace();
  return sessionTrace;
}

/** 登出后调用可重置链路（下个请求生成新 trace），可选。 */
export function resetTrace(): void {
  sessionTrace = null;
}

/** 组装带 trace + JWT 的请求头（供 FormData / 二进制等非 JSON 请求使用）。
 *  不设置 Content-Type：由浏览器按 body 类型自动决定（multipart 需要 boundary）。 */
export function authHeaders(init?: HeadersInit): Headers {
  const headers = new Headers(init);
  headers.set('X-Trace-Id', ensureTrace());
  const token = getToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return headers;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set('Content-Type', 'application/json');
  // 全链路 trace：贯穿整站会话，登录与后续请求一致；后端强制要求携带 X-Trace-Id
  headers.set('X-Trace-Id', ensureTrace());
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
