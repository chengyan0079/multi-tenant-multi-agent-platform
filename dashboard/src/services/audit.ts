/** 审计日志接口（后端 /api/v1/admin/audit，超管专用，只读、无写接口）。 */

import { http } from './http';

export interface AuditItem {
  /** 审计主键是 UUID 字符串，不是自增数字 */
  id: string;
  tenant_id: number;
  /** 操作人用户 ID：审计表只存 ID，没有用户名 */
  user_id: number;
  action: string;
  target: string | null;
  detail: string | null;
  result: string | null;
  trace_id: string | null;
  ip: string | null;
  create_at: string;
}

/**
 * 查询审计日志（后端分页）。
 * tenant_id 不传即全量（仅超管可用）。
 */
export function listAuditLogs(params: { tenant_id?: number; page?: number; page_size?: number } = {}) {
  const qs = new URLSearchParams();
  if (params.tenant_id !== undefined) qs.set('tenant_id', String(params.tenant_id));
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  const s = qs.toString();
  return http.get<{ items: AuditItem[]; total: number; page: number; page_size: number }>(
    `/api/v1/admin/audit/logs${s ? '?' + s : ''}`,
  );
}

/** 审计日志详情。 */
export function getAuditLog(id: string) {
  return http.get<AuditItem>(`/api/v1/admin/audit/logs/${id}`);
}

/** 登录日志条目（agent_login_log）。 */
export interface LoginLogItem {
  id: number;
  user_id: number | null;
  username: string | null;
  tenant_id: number | null;
  login_type: string;
  success: boolean;
  fail_reason: string | null;
  ip: string | null;
  user_agent: string | null;
  client: string | null;
  trace_id: string | null;
  create_at: string;
}

/** 查询登录日志（后端分页，超管可筛租户）。 */
export function listLoginLogs(params: { tenant_id?: number; page?: number; page_size?: number } = {}) {
  const qs = new URLSearchParams();
  if (params.tenant_id !== undefined) qs.set('tenant_id', String(params.tenant_id));
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  const s = qs.toString();
  return http.get<{ items: LoginLogItem[]; total: number; page: number; page_size: number }>(
    `/api/v1/admin/audit/login-logs${s ? '?' + s : ''}`,
  );
}

/** API 调用日志条目（agent_api_call_log）。 */
export interface ApiLogItem {
  id: number;
  trace_id: string | null;
  caller: string | null;
  user_id: number | null;
  tenant_id: number | null;
  method: string;
  path: string;
  route: string | null;
  query_string: string | null;
  status_code: number | null;
  cost_ms: number | null;
  req_time: string;
  create_at: string;
}

/** 查询 API 调用日志（后端分页，超管可筛租户）。 */
export function listApiLogs(params: { tenant_id?: number; page?: number; page_size?: number } = {}) {
  const qs = new URLSearchParams();
  if (params.tenant_id !== undefined) qs.set('tenant_id', String(params.tenant_id));
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  const s = qs.toString();
  return http.get<{ items: ApiLogItem[]; total: number; page: number; page_size: number }>(
    `/api/v1/admin/audit/api-logs${s ? '?' + s : ''}`,
  );
}
