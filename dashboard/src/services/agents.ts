/** Agent 管理接口（后端 /api/v1/admin/agents，租户级）。 */

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
  tenant_id: number;
  agent_type: string;
  name: string;
  description: string | null;
  version: string;
  enabled: boolean;
  registered: boolean;
  input_schema: Record<string, unknown> | null;
  updated_at: string | null;
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

export const setAgentEnabled = (agentType: string, enabled: boolean, tenantId: number) =>
  http.patch<{ agent_type: string; tenant_id: number; enabled: boolean }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/enabled?tenant_id=${tenantId}`,
    { enabled },
  );

export const listAgentTenants = (agentType: string) =>
  http.get<number[]>(`/api/v1/admin/agents/${encodeURIComponent(agentType)}/tenants`);

export const bindAgentTenant = (agentType: string, tenantId: number) =>
  http.post<{ agent_type: string; tenant_id: number }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/tenants?tenant_id=${tenantId}`,
  );

export const unbindAgentTenant = (agentType: string, tenantId: number) =>
  http.delete<{ agent_type: string; tenant_id: number }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/tenants/${tenantId}`,
  );

/** 新增/更新智能体的请求体。 */
export interface AgentPayload {
  tenant_id: number;
  agent_type: string;
  name: string;
  description?: string;
  version: string;
  input_schema?: string | null;
}

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

export const deleteAgent = (agentType: string, tenantId: number) =>
  http.delete<{ agent_type: string }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}?tenant_id=${tenantId}`,
  );

export const listAgentModels = (agentType: string, tenantId: number, params: PageParams = {}) => {
  const qs = new URLSearchParams();
  qs.set('tenant_id', String(tenantId));
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  return http.get<PagedResult<AgentModelBinding>>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/models?${qs.toString()}`,
  );
};

export const addAgentModel = (
  agentType: string,
  tenantId: number,
  payload: { model_id: number; is_default: boolean; priority: number },
) =>
  http.post<{ agent_type: string; model_id: number }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/models?tenant_id=${tenantId}`,
    payload,
  );

export const updateAgentModel = (
  agentType: string,
  tenantId: number,
  modelId: number,
  payload: { is_default?: boolean; priority?: number },
) =>
  http.put<{ agent_type: string; model_id: number }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/models/${modelId}?tenant_id=${tenantId}`,
    payload,
  );

export const removeAgentModel = (agentType: string, tenantId: number, modelId: number) =>
  http.delete<{ agent_type: string; model_id: number }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/models/${modelId}?tenant_id=${tenantId}`,
  );
