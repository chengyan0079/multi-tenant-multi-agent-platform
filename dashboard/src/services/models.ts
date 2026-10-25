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

export const listModels = (modelType?: string) => {
  const query = modelType ? `?model_type=${encodeURIComponent(modelType)}` : '';
  return http.get<{ items: ModelItem[]; total: number }>(`/api/v1/admin/models${query}`);
};

export const createModel = (payload: ModelPayload) =>
  http.post<{ id: number }>('/api/v1/admin/models', payload);

export const updateModel = (modelId: number, payload: ModelPayload) =>
  http.put<{ id: number }>(`/api/v1/admin/models/${modelId}`, payload);

export const deleteModel = (modelId: number) =>
  http.delete<{ id: number }>(`/api/v1/admin/models/${modelId}`);
