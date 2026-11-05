/** 工具与插件接口（/api/v1/admin/plugins），数据源为 agent_plugin 表。 */

import { http } from './http';

export interface PluginItem {
  id: string;
  name: string;
  version: string;
  capabilities: string;
  config: string;
  status: string;
  registered_at: string;
  tenant_id: number;
  user_id: number;
  create_at: string;
  updated_at: string;
}

export interface PluginPayload {
  name: string;
  version: string;
  capabilities: string;
  config: string;
  status: string;
  tenant_id: number;
  user_id: number;
}

export interface PluginPage {
  items: PluginItem[];
  total: number;
  page: number;
  page_size: number;
}

const BASE = '/api/v1/admin/plugins';

export const listPlugins = (params: {
  name?: string;
  status?: string;
  page?: number;
  page_size?: number;
} = {}) => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  });
  const s = qs.toString();
  return http.get<PluginPage>(`${BASE}${s ? '?' + s : ''}`);
};

export const getPlugin = (id: string) => http.get<PluginItem>(`${BASE}/${id}`);

export const createPlugin = (payload: PluginPayload) =>
  http.post<{ id: string }>(BASE, payload);

export const updatePlugin = (id: string, payload: PluginPayload) =>
  http.put<{ id: string }>(`${BASE}/${id}`, payload);

export const deletePlugin = (id: string) =>
  http.delete<{ id: string }>(`${BASE}/${id}`);

export const setPluginStatus = (id: string, status: string) =>
  http.patch<{ id: string; status: string }>(`${BASE}/${id}/status`, { status });
