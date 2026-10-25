/** 配置中心接口（后端 /api/v1/admin/config，超管专用，审批流：申请 → 复核 → 执行写 Nacos）。 */

import { http } from './http';

/** 申请状态：后端 ST_PENDING=0 / ST_APPROVED=1 / ST_REJECTED=2 / ST_EXECUTED=3 */
export const REQUEST_STATUS: Record<number, string> = {
  0: '待审核',
  1: '待执行',
  2: '已驳回',
  3: '已发布',
};

export const OP_TYPE: Record<number, string> = {
  1: '新增',
  2: '修改',
  3: '删除',
  4: '回滚',
};

export interface ConfigRequestItem {
  id: number;
  namespace: string;
  group_id: string;
  data_id: string;
  domain: string;
  op_type: number;
  title: string | null;
  status: number;
  applicant_user_id: string | null;
  reviewer_user_id: string | null;
  create_at: string | null;
}

export const listRequests = (params: { page?: number; page_size?: number; status?: number } = {}) => {
  const query = new URLSearchParams();
  query.set('page', String(params.page ?? 1));
  query.set('page_size', String(params.page_size ?? 20));
  if (params.status !== undefined) {
    query.set('status', String(params.status));
  }
  return http.get<{ items: ConfigRequestItem[]; total: number; page: number; page_size: number }>(
    `/api/v1/admin/config/requests?${query.toString()}`,
  );
};

/* ---------- 状态与动作常量（与后端 ST_* / OP_* / RV_* 对应） ---------- */

export const OP_ADD = 1;
export const OP_MODIFY = 2;
export const OP_DELETE = 3;
export const OP_ROLLBACK = 4;

/** 复核动作：1=通过 2=驳回 */
export const REVIEW_APPROVE = 1;
export const REVIEW_REJECT = 2;

export interface CreateRequestPayload {
  namespace: string;
  group_id: string;
  data_id: string;
  /** 业务域，后端仅用于筛选，常见值 prompt / agent / tool */
  domain: string;
  op_type: number;
  title?: string;
  /** 新增/修改必填；删除时后端会忽略 */
  content_new?: string;
  content_format?: string;
  reason?: string;
}

export interface RollbackPayload {
  namespace: string;
  group_id: string;
  data_id: string;
  domain: string;
  /** 要回滚到的 Nacos 历史版本 id */
  src_history_nid: number;
  title?: string;
  reason?: string;
}

export interface ConfigRequestDetail extends ConfigRequestItem {
  content_format: string | null;
  content_new: string | null;
  /** 旧内容由后端实时从 Nacos 拉取，可能与申请时不同 */
  old_content: string | null;
  reason: string | null;
  src_history_nid: number | null;
  nacos_history_nid: number | null;
  updated_at: string | null;
}

/** 发起配置变更申请（新增/修改/删除） */
export const createRequest = (payload: CreateRequestPayload) =>
  http.post<{ id: number; status: number }>('/api/v1/admin/config/requests', payload);

/** 发起回滚申请（用指定历史版本内容作为拟下发内容） */
export const createRollback = (payload: RollbackPayload) =>
  http.post<{ id: number; status: number }>('/api/v1/admin/config/requests/rollback', payload);

export const getRequestDetail = (requestId: number) =>
  http.get<ConfigRequestDetail>(`/api/v1/admin/config/requests/${requestId}`);

/** 复核：action=1 通过（转待执行）、action=2 驳回 */
export const reviewRequest = (requestId: number, action: number, comment?: string) =>
  http.post<{ id: number; status: number }>(`/api/v1/admin/config/requests/${requestId}/review`, {
    action,
    comment,
  });

/** 执行：只有复核通过的单子才能执行，真正写 Nacos 只发生在这一步 */
export const executeRequest = (requestId: number) =>
  http.post<{ id: number; status: number }>(`/api/v1/admin/config/requests/${requestId}/execute`);
