/** 消息管理接口：后端按角色拆成 /api/v1/admin/messages（超管，可跨租户）与
 *  /api/v1/tenant/messages（租户管理员，强制本租户）两套，前端按角色选基路径。 */

import { http } from './http';
import { isTenantContext } from './auth';
import type { Paged } from './rbac';

export interface OutboxItem {
  id: string;
  topic: string;
  message_kind: string;
  status: string;
  retry_count: number;
  last_error: string | null;
  tenant_id: number | null;
  sent_at?: string;
  create_at: string;
  update_at: string;
}

export interface DeadLetterItem {
  id: string;
  topic: string;
  payload: any;
  origin_queue: string | null;
  error: string | null;
  retry_count: number;
  tenant_id: number | null;
  create_at: string;
}

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') sp.set(k, String(v));
  });
  const s = sp.toString();
  return s ? `?${s}` : '';
}

/** 消息队列（outbox）列表，后端分页；超管可传 tenant_id，租户管理员只看本租户。 */
export async function listMessageQueue(params: {
  page?: number;
  page_size?: number;
  status?: string;
  message_kind?: string;
  tenant_id?: number;
}) {
  if (isTenantContext()) {
    const { page, page_size, status, message_kind } = params;
    return http.get<Paged<OutboxItem>>(`/api/v1/tenant/messages/queue${qs({ page, page_size, status, message_kind })}`);
  }
  return http.get<Paged<OutboxItem>>(`/api/v1/admin/messages/queue${qs(params)}`);
}

/** 死信队列列表，后端分页。 */
export async function listDeadLetters(params: {
  page?: number;
  page_size?: number;
  tenant_id?: number;
}) {
  if (isTenantContext()) {
    const { page, page_size } = params;
    return http.get<Paged<DeadLetterItem>>(`/api/v1/tenant/messages/dead-letters${qs({ page, page_size })}`);
  }
  return http.get<Paged<DeadLetterItem>>(`/api/v1/admin/messages/dead-letters${qs(params)}`);
}

/** 更改消息状态：pending=重投 / done=标记完成 / failed=标记失败。 */
export async function updateMessageStatus(id: string, status: string, error?: string) {
  const base = isTenantContext() ? '/api/v1/tenant/messages' : '/api/v1/admin/messages';
  return http.patch(`${base}/queue/${id}`, error ? { status, error } : { status });
}

/** 消息详情（含 payload）。 */
export async function getOutbox(id: string) {
  const base = isTenantContext() ? '/api/v1/tenant/messages' : '/api/v1/admin/messages';
  return http.get<OutboxItem & { payload?: any }>(`${base}/queue/${id}`);
}

/** 死信详情（含 payload）。 */
export async function getDeadLetter(id: string) {
  const base = isTenantContext() ? '/api/v1/tenant/messages' : '/api/v1/admin/messages';
  return http.get<DeadLetterItem>(`${base}/dead-letters/${id}`);
}
