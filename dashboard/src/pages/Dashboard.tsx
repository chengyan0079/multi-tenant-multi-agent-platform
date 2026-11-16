import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import {
  ApiOutlined,
  ArrowDownOutlined,
  ArrowUpOutlined,
  CheckCircleOutlined,
  MessageOutlined,
  MinusOutlined,
  ReloadOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Grid,
  Row,
  Segmented,
  Skeleton,
  Space,
  Statistic,
  Tag,
  Typography,
  Result,
} from 'antd';
import { ProTable, type ProColumns } from '../components/ProTable';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import {
  getDashboard,
  type ActivityRow,
  type DashboardData,
  type DashboardStat,
  type TenantRankRow,
} from '../services/dashboard';
import { hasScope } from '../services/auth';

const PIE_COLORS = ['#3b5bdb', '#13b5b1', '#22a06b', '#e3a008', '#ef6c4d', '#5b8def'];

/** 四张指标卡的视觉配置：图标 + 主题色，按后端返回的 key 匹配 */
const STAT_DECOR: Record<string, { icon: ReactNode; color: string; tint: string }> = {
  api_calls: { icon: <ApiOutlined />, color: '#3b5bdb', tint: 'rgba(59, 91, 219, 0.12)' },
  active_threads: { icon: <MessageOutlined />, color: '#13b5b1', tint: 'rgba(19, 181, 177, 0.12)' },
  agents: { icon: <RobotOutlined />, color: '#22a06b', tint: 'rgba(34, 160, 107, 0.12)' },
  success_rate: { icon: <CheckCircleOutlined />, color: '#e3a008', tint: 'rgba(227, 160, 8, 0.12)' },
};
const FALLBACK_DECOR = { icon: <ApiOutlined />, color: '#3b5bdb', tint: 'rgba(59, 91, 219, 0.12)' };

const fmtNumber = (value: number): string => value.toLocaleString('zh-CN');

/** 运行时长：秒 → 人话 */
function formatUptime(seconds: number | null): string {
  if (seconds == null) {
    return '—';
  }
  if (seconds < 60) {
    return `${Math.round(seconds)} 秒`;
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)} 分钟`;
  }
  const hours = Math.floor(seconds / 3600);
  return `${hours} 小时 ${Math.floor((seconds % 3600) / 60)} 分`;
}

const activityColumns = [
  {
    title: '时间',
    dataIndex: 'time',
    key: 'time',
    width: 168,
    render: (value: string) => <Typography.Text type="secondary">{value}</Typography.Text>,
  },
  { title: '操作人', dataIndex: 'user', key: 'user', width: 100 },
  {
    title: '动作',
    dataIndex: 'action',
    key: 'action',
    render: (value: string) => <Tag color="blue">{value}</Tag>,
  },
  {
    title: '对象',
    dataIndex: 'target',
    key: 'target',
    ellipsis: true,
    render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
  },
  {
    title: '结果',
    dataIndex: 'result',
    key: 'result',
    width: 90,
    render: (value: string) => {
      const color = value === '成功' ? 'green' : value === '失败' ? 'red' : 'orange';
      return <Tag color={color}>{value}</Tag>;
    },
  },
];

const rankingColumns = [
  {
    title: '租户',
    dataIndex: 'name',
    key: 'name',
    render: (value: string, row: TenantRankRow) => (
      <Space size={6}>
        <span>{value}</span>
        <Typography.Text type="secondary">#{row.tenant_id}</Typography.Text>
        {!row.enabled && <Tag>停用</Tag>}
      </Space>
    ),
  },
  { title: '会话', dataIndex: 'threads', key: 'threads', width: 90 },
  { title: '运行量', dataIndex: 'runs', key: 'runs', width: 100 },
  {
    title: '平均耗时',
    dataIndex: 'avg_cost_ms',
    key: 'avg_cost_ms',
    width: 110,
    render: (value: number | null) => (value == null ? '-' : `${fmtNumber(value)} ms`),
  },
  {
    title: 'Token',
    dataIndex: 'tokens',
    key: 'tokens',
    width: 110,
    render: (value: number) => fmtNumber(value),
  },
];

/** 指标卡：大数字 + 环比，环比上升绿色、下降红色 */
function StatCard({ item }: { item: DashboardStat }) {
  const decor = STAT_DECOR[item.key] ?? FALLBACK_DECOR;
  const up = item.trend > 0;
  const down = item.trend < 0;
  const trendColor = up ? '#22a06b' : down ? '#e5484d' : '#8c8c8c';
  const TrendIcon = up ? ArrowUpOutlined : down ? ArrowDownOutlined : MinusOutlined;

  return (
    <Card className="dash-stat" bordered={false}>
      <Space align="center" size={12} style={{ width: '100%', justifyContent: 'space-between' }}>
        <Statistic
          title={item.title}
          value={item.value}
          precision={item.precision}
          suffix={<span className="dash-stat-suffix">{item.suffix}</span>}
          valueStyle={{ fontSize: 26, fontWeight: 600 }}
        />
        <span className="dash-stat-icon" style={{ color: decor.color, background: decor.tint }}>
          {decor.icon}
        </span>
      </Space>
      <div className="dash-stat-trend" style={{ color: trendColor }}>
        <TrendIcon />
        <span>{item.trend === 0 ? '与上一周期持平' : `${Math.abs(item.trend).toLocaleString('zh-CN')}% 较上一周期`}</span>
      </div>
    </Card>
  );
}

/** 首页：监控概览（对接 /api/v1/dashboard，接口失败时展示错误态，不再使用示例数据兜底） */
export default function Dashboard() {
  const screens = Grid.useBreakpoint();
  const isMobile = screens.lg === false;
  const chartHeight = isMobile ? 200 : 260;

  const [days, setDays] = useState<7 | 30>(7);
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState('');

  const load = useCallback(async (range: number, refresh = false) => {
    if (!hasScope('dashboard:view')) return;
    setLoading(true);
    try {
      const result = await getDashboard(range, undefined, refresh);
      setData(result);
      setError('');
      setUpdatedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    } catch (err) {
      setError(err instanceof Error ? err.message : '看板数据加载失败');
      // 加载失败保留已有数据（如切换周期前的旧数据），不再用示例数据兜底
      setData((prev) => prev);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [days, load]);

  // 计算放在所有提前 return 之前：避免条件调用 Hook 导致
  // "Rendered more hooks than during the previous render" 整页报错。
  const distribution = data?.agent_distribution ?? [];
  const totalCalls = distribution.reduce((sum, item) => sum + Number(item.value || 0), 0);

  if (!hasScope('dashboard:view')) {
    return <Result status="403" title="无权限" subTitle="你没有查看监控概览的权限" />;
  }

  if (loading && !data) {
    return (
      <div className="dash-page">
        <Skeleton active paragraph={{ rows: 2 }} />
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          {[0, 1, 2, 3].map((i) => (
            <Col xs={24} sm={12} xl={6} key={i}>
              <Card bordered={false}>
                <Skeleton active paragraph={{ rows: 1 }} />
              </Card>
            </Col>
          ))}
        </Row>
        <Card bordered={false} style={{ marginTop: 16 }}>
          <Skeleton active paragraph={{ rows: 6 }} />
        </Card>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="dash-page">
        <Result
          status="warning"
          title="看板数据加载失败"
          subTitle={error || '当前没有可用的看板数据'}
          extra={
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load(days)}>
              重试
            </Button>
          }
        />
      </div>
    );
  }

  const view = data;
  const scopeLabel = view.scope.is_super_admin
    ? view.scope.tenant_id == null
      ? '全平台视角'
      : `聚焦租户 #${view.scope.tenant_id}`
    : `本租户视角${view.scope.tenant_id != null ? ` #${view.scope.tenant_id}` : ''}`;

  const hasTrend = view.request_trend.some((p) => p.requests > 0 || p.errors > 0);
  const hasLatency = view.latency_by_hour.some((p) => p.avg > 0);

  return (
    <div className="dash-page">
      <Card className="dash-hero" bordered={false}>
        <div className="dash-hero-main">
          <div>
            <Typography.Text className="dash-hero-eyebrow">
              {view.service.name.toUpperCase()} · {view.service.env.toUpperCase()}
            </Typography.Text>
            <Typography.Title level={3} className="dash-hero-title">
              监控概览
            </Typography.Title>
            <Space size={[6, 6]} wrap>
              <Tag color="blue">{scopeLabel}</Tag>
              <Tag>v{view.service.version}</Tag>
              <Tag color="green">已运行 {formatUptime(view.service.uptime_s)}</Tag>
              {updatedAt ? (
                <Typography.Text type="secondary">更新于 {updatedAt}</Typography.Text>
              ) : null}
            </Space>
          </div>
          <Space wrap>
            <Segmented
              value={days}
              onChange={(value) => setDays(value as 7 | 30)}
              options={[
                { label: '近 7 天', value: 7 },
                { label: '近 30 天', value: 30 },
              ]}
            />
            <Button
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() => void load(days, true)}
            >
              刷新
            </Button>
          </Space>
        </div>
      </Card>

      {error ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 16 }}
          message="看板数据加载失败"
          description={error}
          action={
            <Button size="small" onClick={() => void load(days, true)}>
              重试
            </Button>
          }
        />
      ) : null}

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {view.stats.map((item) => (
          <Col xs={24} sm={12} xl={6} key={item.key}>
            <StatCard item={item} />
          </Col>
        ))}
      </Row>

      {view.global ? (
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col span={24}>
            <Card
              className="dash-card"
              title="平台存量"
              extra={<Typography.Text type="secondary">仅超管可见</Typography.Text>}
            >
              <Row gutter={[16, 16]}>
                <Col xs={12} sm={8} md={4}>
                  <Statistic
                    title="租户"
                    value={view.global.tenants ?? 0}
                    suffix={`/ ${view.global.tenants_enabled ?? 0} 启用`}
                  />
                </Col>
                <Col xs={12} sm={8} md={5}>
                  <Statistic title="账号" value={view.global.users ?? 0} />
                </Col>
                <Col xs={12} sm={8} md={5}>
                  <Statistic
                    title="智能体"
                    value={view.global.agents ?? 0}
                    suffix={`/ ${view.global.agents_enabled ?? 0} 启用`}
                  />
                </Col>
                <Col xs={12} sm={8} md={5}>
                  <Statistic
                    title="模型"
                    value={view.global.models ?? 0}
                    suffix={`/ ${view.global.models_enabled ?? 0} 启用`}
                  />
                </Col>
                <Col xs={12} sm={8} md={5}>
                  <Statistic title="插件" value={view.global.plugins ?? 0} />
                </Col>
              </Row>
            </Card>
          </Col>
        </Row>
      ) : null}

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={16}>
          <Card
            className="dash-card"
            title="请求趋势"
            extra={<Typography.Text type="secondary">按天聚合 · 错误含 4xx / 5xx</Typography.Text>}
          >
            {hasTrend ? (
              <ResponsiveContainer width="100%" height={chartHeight}>
                <AreaChart data={view.request_trend} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                  <defs>
                    <linearGradient id="dashRequests" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#3b5bdb" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#3b5bdb" stopOpacity={0.02} />
                    </linearGradient>
                    <linearGradient id="dashErrors" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#e5484d" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#e5484d" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eef0f5" vertical={false} />
                  <XAxis dataKey="date" tickLine={false} axisLine={false} fontSize={12} />
                  <YAxis tickLine={false} axisLine={false} fontSize={12} width={56} />
                  <Tooltip />
                  <Legend iconType="circle" />
                  <Area
                    type="monotone"
                    dataKey="requests"
                    name="请求数"
                    stroke="#3b5bdb"
                    strokeWidth={2}
                    fill="url(#dashRequests)"
                  />
                  <Area
                    type="monotone"
                    dataKey="errors"
                    name="错误数"
                    stroke="#e5484d"
                    strokeWidth={2}
                    fill="url(#dashErrors)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="区间内暂无请求数据" />
            )}
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card
            className="dash-card"
            title="智能体调用占比"
            extra={<Tag>{fmtNumber(totalCalls)} 次</Tag>}
          >
            {distribution.length > 0 ? (
              <ResponsiveContainer width="100%" height={chartHeight}>
                <PieChart>
                  <Pie
                    data={distribution}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={isMobile ? 45 : 58}
                    outerRadius={isMobile ? 70 : 86}
                    paddingAngle={2}
                    stroke="none"
                  >
                    {distribution.map((_, index) => (
                      <Cell key={index} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value: number) => `${fmtNumber(value)} 次`} />
                  <Legend iconType="circle" verticalAlign="bottom" height={28} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="区间内暂无调用" />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card
            className="dash-card"
            title="Token 与平均耗时趋势"
            extra={
              <Typography.Text type="secondary">
                Token 按天累计 · 耗时按天平均 · 按当前视角过滤
              </Typography.Text>
            }
          >
            {(view.usage_trend ?? []).some((p) => p.tokens > 0 || p.avg_ms > 0) ? (
              <ResponsiveContainer width="100%" height={chartHeight}>
                <ComposedChart
                  data={view.usage_trend ?? []}
                  margin={{ top: 8, right: 12, left: -12, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="dashTokens" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#13b5b1" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#13b5b1" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eef0f5" vertical={false} />
                  <XAxis dataKey="date" tickLine={false} axisLine={false} fontSize={12} />
                  <YAxis
                    yAxisId="left"
                    tickLine={false}
                    axisLine={false}
                    fontSize={12}
                    width={64}
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tickLine={false}
                    axisLine={false}
                    fontSize={12}
                    width={64}
                    unit="ms"
                  />
                  <Tooltip />
                  <Legend iconType="circle" />
                  <Area
                    yAxisId="left"
                    type="monotone"
                    dataKey="tokens"
                    name="Token（当日累计）"
                    stroke="#13b5b1"
                    strokeWidth={2}
                    fill="url(#dashTokens)"
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="avg_ms"
                    name="平均耗时"
                    stroke="#e3a008"
                    strokeWidth={2}
                    dot={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="区间内暂无 Token / 耗时数据" />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={10}>
          <Card
            className="dash-card"
            title="时段平均耗时"
            extra={<Typography.Text type="secondary">每 4 小时一桶</Typography.Text>}
          >
            {hasLatency ? (
              <ResponsiveContainer width="100%" height={chartHeight}>
                <BarChart data={view.latency_by_hour} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                  <defs>
                    <linearGradient id="dashLatency" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#3b5bdb" stopOpacity={0.9} />
                      <stop offset="100%" stopColor="#5cc8c0" stopOpacity={0.55} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eef0f5" vertical={false} />
                  <XAxis dataKey="hour" tickLine={false} axisLine={false} fontSize={12} />
                  <YAxis tickLine={false} axisLine={false} fontSize={12} width={56} unit="ms" />
                  <Tooltip formatter={(value: number) => `${fmtNumber(value)} ms`} />
                  <Bar dataKey="avg" name="平均耗时" fill="url(#dashLatency)" radius={[6, 6, 0, 0]} maxBarSize={36} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="区间内暂无调用记录" />
            )}
          </Card>
        </Col>
        <Col xs={24} xl={14}>
          <Card
            className="dash-card"
            title="最近活动"
            extra={<Typography.Text type="secondary">最新 5 条审计/调用事件</Typography.Text>}
          >
            <ProTable<ActivityRow>
              search={false}
              options={{ fullScreen: true, setting: true, density: true, reload: false }}
              cardProps={{ styles: { body: { padding: 0 } } }}
              size="small"
              rowKey="key"
              pagination={false}
              columns={activityColumns as ProColumns<ActivityRow>[]}
              dataSource={view.recent_activities}
              scroll={{ x: 520 }}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无审计事件" /> }}
            />
          </Card>
        </Col>
      </Row>

      {view.tenant_ranking && view.tenant_ranking.length > 0 ? (
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col span={24}>
            <Card className="dash-card" title="租户用量排行" extra={<Typography.Text type="secondary">仅超管可见</Typography.Text>}>
              <ProTable<TenantRankRow>
                search={false}
                options={{ fullScreen: true, setting: true, density: true, reload: false }}
                cardProps={{ styles: { body: { padding: 0 } } }}
                size="small"
                rowKey="tenant_id"
                pagination={false}
                columns={rankingColumns as ProColumns<TenantRankRow>[]}
                dataSource={view.tenant_ranking}
                scroll={{ x: 480 }}
              />
            </Card>
          </Col>
        </Row>
      ) : null}
    </div>
  );
}
