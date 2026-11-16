/** 工具管理接口（/api/v1/admin/tools），数据源 agent_tool（租户级）。 */

import { http } from './http';

export interface ToolItem {
  id: string;
  tenant_id: number;
  name: string;
  plugin: string;
  description: string;
  schema: string;
  config: string;
  enabled: boolean;
  create_at: string;
  updated_at: string;
}

export interface ToolPayload {
  tenant_id: number;
  name: string;
  plugin?: string;
  description?: string;
  schema?: string;
  config?: string;
  enabled?: boolean;
}

export interface ToolPage {
  items: ToolItem[];
  total: number;
  page: number;
  page_size: number;
}

const BASE = '/api/v1/admin/tools';

export const listTools = (params: {
  tenant_id?: number;
  name?: string;
  enabled?: boolean;
  page?: number;
  page_size?: number;
} = {}) => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  });
  const s = qs.toString();
  return http.get<ToolPage>(`${BASE}${s ? '?' + s : ''}`);
};

export const getTool = (id: string) => http.get<ToolItem>(`${BASE}/${id}`);

export const createTool = (payload: ToolPayload) => http.post<{ id: string }>(BASE, payload);

export const updateTool = (id: string, payload: ToolPayload) =>
  http.put<{ updated: number }>(`${BASE}/${id}`, payload);

export const setToolEnabled = (id: string, enabled: boolean) =>
  http.patch<{ updated: number }>(`${BASE}/${id}/enabled`, { enabled });

export const deleteTool = (id: string) => http.delete<{ deleted: number }>(`${BASE}/${id}`);
