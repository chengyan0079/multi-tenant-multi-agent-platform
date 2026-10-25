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
 * 查询审计日志。
 *
 * 后端按 create_at 倒序返回、只有 limit 没有 offset，所以分页在前端做。
 * tenant_id 不传即全量（仅超管可用）。
 */
export function listAuditLogs(params: { tenant_id?: number; limit?: number } = {}) {
  const qs = new URLSearchParams();
  if (params.tenant_id !== undefined) qs.set('tenant_id', String(params.tenant_id));
  qs.set('limit', String(params.limit ?? 200));
  return http.get<{ items: AuditItem[]; total: number }>(
    `/api/v1/admin/audit/logs?${qs.toString()}`,
  );
}
