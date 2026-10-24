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
