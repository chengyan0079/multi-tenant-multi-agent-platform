/** 配置中心接口（后端 /api/v1/admin/config）。
 * 配置读取直接走 Nacos（list/detail/history/groups）；审批流：申请 → 复核 → 执行写 Nacos。 */

import { http } from './http';

/** 申请状态：后端 ST_PENDING=0 / ST_APPROVED=1 / ST_REJECTED=2 / ST_EXECUTED=3 / ST_WITHDRAWN=4 */
export const REQUEST_STATUS: Record<number, string> = {
  0: '待审核',
  1: '待执行',
  2: '已驳回',
  3: '已发布',
  4: '已撤回',
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
  op_type: number;
  title: string | null;
  status: number;
  applicant_user_id: string | null;
  applicant_name?: string | null;
  reviewer_user_id: string | null;
  reviewer_name?: string | null;
  /** 生效时间：审批单进入终态（驳回/已发布/已撤回）时写入，其余为空 */
  effective_at?: string | null;
  create_at: string | null;
}

/** 审核日志（agent_config_review 全量记录，已关联复核人用户名与动作名） */
export interface ReviewLogItem {
  id: number;
  approval_id: number;
  reviewer_user_id: number | null;
  reviewer_name?: string | null;
  action: number;
  action_name?: string | null;
  comment: string | null;
  create_at: string | null;
  namespace: string | null;
  group_id: string | null;
  data_id: string | null;
  op_type: number | null;
  op_type_name?: string | null;
  title: string | null;
  approval_status: number | null;
}

export const listReviewLogs = (params: { page?: number; page_size?: number } = {}) => {
  const query = new URLSearchParams();
  query.set('page', String(params.page ?? 1));
  query.set('page_size', String(params.page_size ?? 20));
  return http.get<{ items: ReviewLogItem[]; total: number; page: number; page_size: number }>(
    `/api/v1/admin/config/reviews?${query.toString()}`,
  );
};

export const listRequests = (params: { page?: number; page_size?: number; status?: number; group_id?: string } = {}) => {
  const query = new URLSearchParams();
  query.set('page', String(params.page ?? 1));
  query.set('page_size', String(params.page_size ?? 20));
  if (params.status !== undefined) query.set('status', String(params.status));
  if (params.group_id) query.set('group_id', params.group_id);
  return http.get<{ items: ConfigRequestItem[]; total: number; page: number; page_size: number }>(
    `/api/v1/admin/config/requests?${query.toString()}`,
  );
};

/* ---------- 状态与动作常量（与后端 ST_* / OP_* / RV_* 对应） ---------- */
export const OP_ADD = 1;
export const OP_MODIFY = 2;
export const OP_DELETE = 3;
export const OP_ROLLBACK = 4;
export const REVIEW_APPROVE = 1;
export const REVIEW_REJECT = 2;

export interface ConfigApplyPayload {
  namespace: string;
  group_id: string;
  data_id: string;
  title?: string;
  content_new?: string;
  content_format?: string;
  reason?: string;
}

export interface NacosHistoryDetail {
  nid?: number;
  dataId?: string;
  groupName?: string;
  md5?: string;
  content?: string;
  createdTime?: string;
  [key: string]: unknown;
}

export interface RollbackPayload {
  namespace: string;
  group_id: string;
  data_id: string;
  src_history_nid: number;
  content_format?: string;
  title?: string;
  reason?: string;
}

export interface ConfigRequestDetail extends ConfigRequestItem {
  content_format: string | null;
  content_new: string | null;
  old_content: string | null;
  reason: string | null;
  src_history_nid: number | null;
  nacos_history_nid: number | null;
  updated_at: string | null;
}

/** 新增配置申请 */
export const addConfig = (payload: ConfigApplyPayload) =>
  http.post<{ id: number; status: number }>('/api/v1/admin/config/requests/add', payload);

/** 修改配置申请 */
export const modifyConfig = (payload: ConfigApplyPayload) =>
  http.post<{ id: number; status: number }>('/api/v1/admin/config/requests/modify', payload);

/** 删除配置申请（无需内容，content_format 为真实类型，作记录展示） */
export const deleteConfig = (payload: { namespace: string; group_id: string; data_id: string; content_format?: string; title?: string; reason?: string }) =>
  http.post<{ id: number; status: number }>('/api/v1/admin/config/requests/delete', payload);

/** 发起回滚申请（用指定历史版本内容作为拟下发内容） */
export const createRollback = (payload: RollbackPayload) =>
  http.post<{ id: number; status: number }>('/api/v1/admin/config/requests/rollback', payload);

export const getRequestDetail = (requestId: number) =>
  http.get<ConfigRequestDetail>(`/api/v1/admin/config/requests/${requestId}`);

/** 审批通过（通过即写 Nacos） */
export const approveRequest = (requestId: number, comment?: string) => {
  const query = new URLSearchParams();
  if (comment) query.set('comment', comment);
  return http.post<{ id: number; status: number }>(`/api/v1/admin/config/requests/${requestId}/approve?${query.toString()}`);
};

/** 驳回 */
export const rejectRequest = (requestId: number, comment?: string) => {
  const query = new URLSearchParams();
  if (comment) query.set('comment', comment);
  return http.post<{ id: number; status: number }>(`/api/v1/admin/config/requests/${requestId}/reject?${query.toString()}`);
};

/** 撤回自己的待复核申请（后端校验仅本人 + 仅待复核） */
export const withdrawRequest = (requestId: number) =>
  http.post<{ id: number; status: number }>(`/api/v1/admin/config/requests/${requestId}/withdraw`);

/* ---------- 直读 Nacos ---------- */
export interface NacosConfigItem {
  dataId: string;
  groupName: string;
  md5?: string;
  type?: string;
  /** 创建时间（Nacos 详情回查补齐，epoch 毫秒或 ISO 字符串） */
  createTime?: string | number;
  /** 修改时间（同上） */
  modifyTime?: string | number;
  lastModified?: string | number;
}

export const listConfigs = (params: { group?: string; data_id?: string; page_no?: number; page_size?: number } = {}) => {
  const query = new URLSearchParams();
  if (params.group) query.set('group', params.group);
  if (params.data_id) query.set('data_id', params.data_id);
  query.set('page_no', String(params.page_no ?? 1));
  query.set('page_size', String(params.page_size ?? 20));
  return http.get<{ totalCount: number; pageNumber: number; pagesAvailable: number; pageItems: NacosConfigItem[] }>(
    `/api/v1/admin/config/list?${query.toString()}`,
  );
};

export const listGroups = () =>
  http.get<{ groups: string[] }>('/api/v1/admin/config/groups');

export const getConfigDetail = (dataId: string, group?: string) => {
  const query = new URLSearchParams();
  query.set('data_id', dataId);
  if (group) query.set('group', group);
  return http.get<{
    data_id: string;
    group: string | null;
    content: string | null;
    type?: string | null;
    md5?: string | null;
    createTime?: string | number | null;
    modifyTime?: string | number | null;
    lastModified?: string | number | null;
  }>(`/api/v1/admin/config/detail?${query.toString()}`);
};

export interface NacosHistoryItem {
  nid: number;
  dataId: string;
  groupName: string;
  md5?: string;
  content?: string;
  createdTime?: string;
}

export const listHistory = (dataId: string, group?: string, page = 1) => {
  const query = new URLSearchParams();
  query.set('data_id', dataId);
  if (group) query.set('group', group);
  query.set('page', String(page));
  return http.get<{ totalCount: number; pageNumber: number; pagesAvailable: number; pageItems: NacosHistoryItem[] }>(
    `/api/v1/admin/config/history?${query.toString()}`,
  );
};

/** 配置历史版本详情（按 nid 读取某一版本内容） */
export const getHistoryDetail = (dataId: string, nid: number, group?: string) => {
  const query = new URLSearchParams();
  query.set('data_id', dataId);
  query.set('nid', String(nid));
  if (group) query.set('group', group);
  return http.get<NacosHistoryDetail>(`/api/v1/admin/config/history/detail?${query.toString()}`);
};

/* ---------- 审核历史（agent_config_review，按 approval_id 弹窗查看） ---------- */
export interface ConfigReviewItem {
  id: number;
  approval_id: number;
  reviewer_user_id: string | null;
  reviewer_name?: string | null;
  action: number;
  comment: string | null;
  create_at: string | null;
}

export const getReviews = (requestId: number) =>
  http.get<{ items: ConfigReviewItem[] }>(`/api/v1/admin/config/requests/${requestId}/reviews`);
