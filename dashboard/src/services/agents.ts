/** Agent 管理接口（后端 /api/v1/admin/agents，超管专用）。 */

import { http } from './http';

export interface PagedResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface PageParams {
  page?: number;
  page_size?: number;
}

export interface AgentItem {
  agent_type: string;
  name: string;
  description: string | null;
  version: string;
  enabled: boolean;
  registered: boolean;
  input_schema: Record<string, unknown> | null;
  updated_at: string | null;
}

export interface CapabilityItem {
  agent_type: string;
  name: string;
  global_enabled: boolean;
  enabled: boolean;
  configured: boolean;
}

export const listAgents = (params: PageParams & { tenant_id?: number; only_enabled?: boolean } = {}) => {
  const qs = new URLSearchParams();
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  if (params.tenant_id !== undefined) qs.set('tenant_id', String(params.tenant_id));
  if (params.only_enabled !== undefined) qs.set('only_enabled', String(params.only_enabled));
  const s = qs.toString();
  return http.get<PagedResult<AgentItem>>(`/api/v1/admin/agents${s ? '?' + s : ''}`);
};

export const setAgentEnabled = (agentType: string, enabled: boolean) =>
  http.patch<{ agent_type: string; enabled: boolean }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/enabled`,
    { enabled },
  );

export const listCapabilities = (tenantId: number, params: PageParams = {}) => {
  const qs = new URLSearchParams();
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  const s = qs.toString();
  return http.get<PagedResult<CapabilityItem>>(
    `/api/v1/admin/agents/tenants/${tenantId}/capabilities${s ? '?' + s : ''}`,
  );
};

export const setCapabilities = (
  tenantId: number,
  items: { agent_type: string; enabled: boolean }[],
) =>
  http.put<{ tenant_id: number; updated: number }>(
    `/api/v1/admin/agents/tenants/${tenantId}/capabilities`,
    items,
  );

/** 新增/更新智能体的请求体（input_schema 为 JSON 文本，可空）。 */
export interface AgentPayload {
  agent_type: string;
  name: string;
  description?: string;
  version: string;
  enabled: boolean;
  input_schema?: string | null;
}

/** 智能体 ↔ 模型绑定项（含模型展示信息）。 */
export interface AgentModelBinding {
  agent_id: number;
  model_id: number;
  is_default: boolean;
  priority: number;
  model_type: string;
  name: string;
  provider: string | null;
  model_enabled: boolean;
}

export const createAgent = (payload: AgentPayload) =>
  http.post<{ id: number; agent_type: string }>('/api/v1/admin/agents', payload);

export const updateAgent = (agentType: string, payload: AgentPayload) =>
  http.put<{ agent_type: string }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}`,
    payload,
  );

export const deleteAgent = (agentType: string) =>
  http.delete<{ agent_type: string }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}`,
  );

export const listAgentModels = (agentType: string, params: PageParams = {}) => {
  const qs = new URLSearchParams();
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  const s = qs.toString();
  return http.get<PagedResult<AgentModelBinding>>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/models${s ? '?' + s : ''}`,
  );
};

export const addAgentModel = (
  agentType: string,
  payload: { model_id: number; is_default: boolean; priority: number },
) =>
  http.post<{ agent_type: string; model_id: number }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/models`,
    payload,
  );

export const updateAgentModel = (
  agentType: string,
  modelId: number,
  payload: { is_default?: boolean; priority?: number },
) =>
  http.put<{ agent_type: string; model_id: number }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/models/${modelId}`,
    payload,
  );

export const removeAgentModel = (agentType: string, modelId: number) =>
  http.delete<{ agent_type: string; model_id: number }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/models/${modelId}`,
  );
