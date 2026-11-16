/** 变更发布（沙箱验证）接口。 */

import { http } from './http';

const BASE = '/api/v1/tenant/db_change';

export interface ReleaseResult {
  ok: boolean;
  thread_id?: string;
  request_id?: number;
  final_sql?: string | null;
  exec_result?: Record<string, unknown>;
  release_status?: string;
  status?: string;
  answer?: string;
  gate?: string;
}

export const releaseChange = (
  requestId: number,
  sandboxConnectionId: string,
  execute = true,
) =>
  http.post<ReleaseResult>(`${BASE}/${requestId}/release`, {
    sandbox_connection_id: sandboxConnectionId,
    execute,
  });

export const getRelease = (requestId: number) =>
  http.get<Record<string, unknown> | null>(`${BASE}/${requestId}/release`);

export const approveRelease = (
  threadId: string,
  payload: { approved: boolean; comment?: string },
) => http.post<{ ok: boolean; release_status?: string; final_sql?: string }>(
  `${BASE}/release/${threadId}/approve`,
  payload,
);
