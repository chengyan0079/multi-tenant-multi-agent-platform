/** 首页监控/统计页的示例数据（后端不可用时的兜底展示） */

import type {
  ActivityRow,
  DashboardData,
  DashboardStat,
  DistributionItem,
  LatencyPoint,
  TrendPoint,
} from '../services/dashboard';

export const overviewStats: DashboardStat[] = [
  { key: 'api_calls', title: '今日调用量', value: 12864, suffix: '次', precision: 0, trend: 12.5 },
  { key: 'active_threads', title: '活跃会话', value: 342, suffix: '个', precision: 0, trend: 8.2 },
  { key: 'agents', title: '智能体总数', value: 12, suffix: '个', precision: 0, trend: 2.0 },
  { key: 'success_rate', title: '平均成功率', value: 99.2, suffix: '%', precision: 1, trend: 0.4 },
];

/** 近 7 天请求趋势 */
export const requestTrend: TrendPoint[] = [
  { date: '10-18', requests: 9800, errors: 120 },
  { date: '10-19', requests: 10420, errors: 96 },
  { date: '10-20', requests: 11260, errors: 134 },
  { date: '10-21', requests: 10880, errors: 88 },
  { date: '10-22', requests: 12140, errors: 102 },
  { date: '10-23', requests: 12680, errors: 76 },
  { date: '10-24', requests: 12864, errors: 64 },
];

/** 各智能体调用占比 */
export const agentDistribution: DistributionItem[] = [
  { name: 'QA 问答', value: 4820 },
  { name: '简历审查', value: 2610 },
  { name: '模拟面试', value: 1980 },
  { name: '试卷批改', value: 1740 },
  { name: '知识库', value: 1714 },
];

/** 各时段平均响应耗时（ms） */
export const latencyByHour: LatencyPoint[] = [
  { hour: '00', avg: 320 },
  { hour: '04', avg: 280 },
  { hour: '08', avg: 460 },
  { hour: '12', avg: 620 },
  { hour: '16', avg: 580 },
  { hour: '20', avg: 410 },
];

/** 最近活动 */
export const recentActivities: ActivityRow[] = [
  { key: '1', time: '2026-10-24 10:32:11', user: 'admin', action: '配置变更', target: 'qa.prompt.template', result: '成功' },
  { key: '2', time: '2026-10-24 10:28:03', user: 'admin', action: '智能体上线', target: 'exam-grading-agent', result: '成功' },
  { key: '3', time: '2026-10-24 10:15:47', user: 'system', action: '人工转接', target: 'thread-9f2c1a', result: '待处理' },
  { key: '4', time: '2026-10-24 09:58:20', user: 'admin', action: '角色分配', target: 'user=1001 tenant=200', result: '成功' },
  { key: '5', time: '2026-10-24 09:41:09', user: 'system', action: '工具调用失败', target: 'resume-parser', result: '失败' },
];

/** 整页兜底数据：接口不可用时保持页面结构完整，并明确标注「示例数据」 */
export const sampleDashboard: DashboardData = {
  scope: { is_super_admin: false, tenant_id: null, days: 7, since: '' },
  service: { name: 'agent-platform', version: '0.1.0', env: 'dev', uptime_s: null },
  stats: overviewStats,
  request_trend: requestTrend,
  agent_distribution: agentDistribution,
  latency_by_hour: latencyByHour,
  recent_activities: recentActivities,
};
