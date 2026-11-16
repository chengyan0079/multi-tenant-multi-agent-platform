/** 数据库变更评审接口（/api/v1/tenant/db_change）。 */

import { http } from './http';

export interface SubmitPayload {
  sql_text: string;
  db_type: string;
  connection_id: string;
  target_database?: string;
  target_tables?: string[];
  script_file_id?: number;
  drill_file_id?: number;
}

export interface ReviewResult {
  ok: boolean;
  thread_id?: string;
  request_id?: number;
  risk_level?: string;
  answer?: string;
  suggestions?: string[];
  metadata?: Record<string, unknown>;
  slow_sql?: Record<string, unknown>;
  status?: string;
  gate?: string;
  errors?: string[];
  warnings?: string[];
}

export interface ChangeItem {
  id: number;
  title: string;
  target_database: string;
  db_type: string;
  risk_level: string | null;
  status: string;
  /** 图 thread_id（HITL 恢复用；行内审批用） */
  thread_id?: string | null;
  create_at: string;
}

const BASE = '/api/v1/tenant/db_change';

export const submitChange = (payload: SubmitPayload) => http.post<ReviewResult>(BASE, payload);

export const listChanges = (params: { status?: string; page?: number; page_size?: number } = {}) => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  });
  const s = qs.toString();
  return http.get<{ items: ChangeItem[]; total: number; page: number; page_size: number }>(
    `${BASE}${s ? '?' + s : ''}`,
  );
};

export const getChange = (id: number) =>
  http.get<{ request: Record<string, unknown>; review: Record<string, unknown> | null }>(
    `${BASE}/${id}`,
  );

export const approveChange = (threadId: string, payload: { approved: boolean; comment?: string }) =>
  http.post<{ ok: boolean; status: string; risk_level?: string }>(
    `${BASE}/${threadId}/approve`,
    payload,
  );

export interface WorkflowView {
  request: Record<string, unknown> | null;
  review: Record<string, unknown> | null;
  release: Record<string, unknown> | null;
  stage: string;
  stage_hint: string;
  next_actions: string[];
}

export const getWorkflow = (requestId: number) =>
  http.get<WorkflowView>(`${BASE}/${requestId}/workflow`);

export const advanceWorkflow = (
  requestId: number,
  payload: {
    action: string;
    thread_id?: string;
    sandbox_connection_id?: string;
  },
) =>
  http.post<Record<string, unknown>>(`${BASE}/${requestId}/advance`, payload);

export const uploadReviewFile = (
  file: File,
  kind: 'script' | 'drill',
  dbType?: string,
  requestId?: number,
) => {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('kind', kind);
  if (dbType) fd.append('db_type', dbType);
  if (requestId) fd.append('request_id', String(requestId));
  return http.post<{ file_id: number; file_uuid: string; object_key: string; kind: string }>(
    '/api/v1/tenant/db-review/upload',
    fd,
  );
};
