/**
 * 监控看板接口（后端 GET /api/v1/dashboard）
 *
 * 后端按页面 5 个区块组装数据，字段名与图表 dataIndex 对齐，前端不再需要 mock。
 * 权限：平台超管看全平台（可传 tenant_id 聚焦某租户），租户管理员只看本租户。
 */
import { http } from './http';

export interface DashboardStat {
  key: string;
  title: string;
  value: number;
  suffix: string;
  precision: number;
  trend: number;
}

export interface TrendPoint {
  date: string;
  requests: number;
  errors: number;
}

export interface DistributionItem {
  name: string;
  value: number;
}

export interface LatencyPoint {
  hour: string;
  avg: number;
}

export interface ActivityRow {
  key: string;
  time: string;
  user: string;
  action: string;
  target: string;
  result: string;
}

export interface DashboardScope {
  is_super_admin: boolean;
  tenant_id: number | null;
  days: number;
  since: string;
}

export interface DashboardService {
  name: string;
  version: string;
  env: string;
  uptime_s: number | null;
}

export interface TenantRankRow {
  tenant_id: number;
  name: string;
  enabled: boolean;
  threads: number;
  runs: number;
  tokens: number;
  avg_cost_ms: number | null;
}

export interface UsagePoint {
  date: string;
  tokens: number;
  avg_ms: number;
}

export interface DashboardData {
  scope: DashboardScope;
  service: DashboardService;
  stats: DashboardStat[];
  request_trend: TrendPoint[];
  agent_distribution: DistributionItem[];
  latency_by_hour: LatencyPoint[];
  recent_activities: ActivityRow[];
  usage_trend: UsagePoint[];
  /** 以下仅超管返回 */
  global?: Record<string, number>;
  tenant_ranking?: TenantRankRow[];
}

export function getDashboard(
  days = 7,
  tenantId?: number,
  refresh = false,
): Promise<DashboardData> {
  const query = new URLSearchParams({ days: String(days) });
  if (tenantId != null) {
    query.set('tenant_id', String(tenantId));
  }
  if (refresh) {
    query.set('refresh', 'true');
  }
  return http.get<DashboardData>(`/api/v1/dashboard?${query.toString()}`);
}
