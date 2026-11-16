/** 图状态（LangGraph checkpoints）查询接口。 */

import { http } from './http';

export interface GraphStateItem {
  thread_id: string;
  checkpoint_ns: string;
  checkpoint_id: string;
  parent_checkpoint_id: string | null;
  type: string;
  metadata: Record<string, unknown>;
}

export interface GraphStatePage {
  items: GraphStateItem[];
  total: number;
  page: number;
  page_size: number;
}

const BASE = '/api/v1/tenant/graph-states';

export const listGraphStates = (
  params: { thread_id?: string; page?: number; page_size?: number } = {},
) => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  });
  const s = qs.toString();
  return http.get<GraphStatePage>(`${BASE}${s ? '?' + s : ''}`);
};
