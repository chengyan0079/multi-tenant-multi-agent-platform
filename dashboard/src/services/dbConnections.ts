/** 数据库数据源接口（/api/v1/tenant/db-connections，租户下）。 */

import { http } from './http';

export interface DbConnectionItem {
  id: string;
  tenant_id: number;
  name: string;
  db_type: string;
  host: string;
  port: number;
  username: string;
  database: string;
  schema_name?: string;
  readonly: boolean;
  enabled: boolean;
  env?: string;
  remark?: string;
  create_at: string;
  updated_at: string;
}

export interface DbConnectionPayload {
  name: string;
  db_type: string;
  host: string;
  port: number;
  username: string;
  password: string;
  database: string;
  schema_name?: string;
  readonly?: boolean;
  enabled?: boolean;
  remark?: string;
}

export interface DbConnectionPage {
  items: DbConnectionItem[];
  total: number;
  page: number;
  page_size: number;
}

const BASE = '/api/v1/tenant/db-connections';

export const listDbConnections = (params: {
  name?: string;
  page?: number;
  page_size?: number;
} = {}) => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  });
  const s = qs.toString();
  return http.get<DbConnectionPage>(`${BASE}${s ? '?' + s : ''}`);
};

export const getDbConnection = (id: string) => http.get<DbConnectionItem>(`${BASE}/${id}`);

export const createDbConnection = (payload: DbConnectionPayload) =>
  http.post<{ id: string }>(BASE, payload);

export const updateDbConnection = (id: string, payload: DbConnectionPayload) =>
  http.put<{ updated: number }>(`${BASE}/${id}`, payload);

export const setDbConnectionEnabled = (id: string, enabled: boolean) =>
  http.patch<{ updated: number }>(`${BASE}/${id}/enabled`, { enabled });

export const deleteDbConnection = (id: string) =>
  http.delete<{ deleted: number }>(`${BASE}/${id}`);

export const testDbConnection = (id: string) =>
  http.post<{ ok: boolean; error?: string }>(`${BASE}/${id}/test`);
