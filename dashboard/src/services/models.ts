/** 模型注册表接口（后端 /api/v1/admin/models，超管专用；平台级全局资源，不分租户）。 */

import { http } from './http';

export interface ModelItem {
  id: number;
  /** llm / embedding / reranker / classifier */
  model_type: string;
  name: string;
  provider: string | null;
  base_url: string | null;
  /** 后端脱敏返回，有值时为 "***" */
  api_key: string | null;
  endpoint_path: string | null;
  temperature: number | null;
  timeout_s: number | null;
  max_retries: number | null;
  enabled: boolean;
  sort_order: number;
  description: string | null;
  updated_at: string | null;
}

export interface ModelPayload {
  model_type: string;
  name: string;
  provider?: string;
  base_url?: string;
  /** 不传表示保留库里的原值（后端在更新时回填原 key） */
  api_key?: string;
  endpoint_path?: string;
  temperature?: number;
  timeout_s?: number;
  max_retries?: number;
  enabled: boolean;
  sort_order: number;
  description?: string;
}

export const MODEL_TYPES = [
  { value: 'llm', label: 'llm（对话模型）' },
  { value: 'embedding', label: 'embedding（向量化）' },
  { value: 'reranker', label: 'reranker（重排）' },
  { value: 'classifier', label: 'classifier（分类）' },
];

export const listModels = (params: { model_type?: string; page?: number; page_size?: number } = {}) => {
  const qs = new URLSearchParams();
  if (params.model_type) qs.set('model_type', params.model_type);
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  const s = qs.toString();
  return http.get<{ items: ModelItem[]; total: number; page: number; page_size: number }>(
    `/api/v1/admin/models${s ? '?' + s : ''}`,
  );
};

export const getModel = (id: number) =>
  http.get<ModelItem>(`/api/v1/admin/models/${id}`);

export const createModel = (payload: ModelPayload) =>
  http.post<{ id: number }>('/api/v1/admin/models', payload);

export const updateModel = (modelId: number, payload: ModelPayload) =>
  http.put<{ id: number }>(`/api/v1/admin/models/${modelId}`, payload);

export const deleteModel = (modelId: number) =>
  http.delete<{ id: number }>(`/api/v1/admin/models/${modelId}`);

/** 模型启停（status 端点）。 */
export const setModelStatus = (modelId: number, enabled: boolean) =>
  http.patch<{ id: number; enabled: boolean }>(
    `/api/v1/admin/models/${modelId}/status`,
    { enabled },
  );
