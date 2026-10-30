/** Agent 管理接口（后端 /api/v1/admin/agents，超管专用）。 */

import { http } from './http';

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

export const listAgents = () => http.get<{ items: AgentItem[]; total: number }>('/api/v1/admin/agents');

export const setAgentEnabled = (agentType: string, enabled: boolean) =>
  http.patch<{ agent_type: string; enabled: boolean }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/enabled`,
    { enabled },
  );

export const listCapabilities = (tenantId: number) =>
  http.get<{ items: CapabilityItem[]; total: number }>(
    `/api/v1/admin/agents/tenants/${tenantId}/capabilities`,
  );

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

export const listAgentModels = (agentType: string) =>
  http.get<{ items: AgentModelBinding[]; total: number }>(
    `/api/v1/admin/agents/${encodeURIComponent(agentType)}/models`,
  );

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
