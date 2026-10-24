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
