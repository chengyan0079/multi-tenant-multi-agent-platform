import { useCallback, useEffect, useMemo, useState } from 'react';
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
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { sampleDashboard } from '../mock/dashboard';
import {
  getDashboard,
  type ActivityRow,
  type DashboardData,
  type DashboardStat,
  type TenantRankRow,
} from '../services/dashboard';

const PIE_COLORS = ['#1677ff', '#52c41a', '#faad14', '#eb2f96', '#722ed1', '#13c2c2'];

/** 四张指标卡的视觉配置：图标 + 主题色，按后端返回的 key 匹配 */
const STAT_DECOR: Record<string, { icon: ReactNode; color: string; tint: string }> = {
  api_calls: { icon: <ApiOutlined />, color: '#1677ff', tint: 'rgba(22, 119, 255, 0.12)' },
  active_threads: { icon: <MessageOutlined />, color: '#722ed1', tint: 'rgba(114, 46, 209, 0.12)' },
  agents: { icon: <RobotOutlined />, color: '#13c2c2', tint: 'rgba(19, 194, 194, 0.12)' },
  success_rate: { icon: <CheckCircleOutlined />, color: '#52c41a', tint: 'rgba(82, 196, 26, 0.12)' },
};
const FALLBACK_DECOR = { icon: <ApiOutlined />, color: '#1677ff', tint: 'rgba(22, 119, 255, 0.12)' };

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
  const trendColor = up ? '#52c41a' : down ? '#ff4d4f' : '#8c8c8c';
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

/** 首页：监控概览（对接 /api/v1/dashboard，接口不可用时退回示例数据） */
export default function Dashboard() {
  const screens = Grid.useBreakpoint();
  const isMobile = screens.lg === false;
  const chartHeight = isMobile ? 200 : 260;

  const [days, setDays] = useState<7 | 30>(7);
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState('');
  const [isSample, setIsSample] = useState(false);

  const load = useCallback(async (range: number) => {
    setLoading(true);
    try {
      const result = await getDashboard(range);
      setData(result);
      setIsSample(false);
      setError('');
      setUpdatedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    } catch (err) {
      setError(err instanceof Error ? err.message : '看板数据加载失败');
      // 没拿到过真实数据时用示例数据兜底，避免整页空白
      setData((prev) => prev ?? sampleDashboard);
      setIsSample(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [days, load]);

  const view = data ?? sampleDashboard;
  const scopeLabel = view.scope.is_super_admin
    ? view.scope.tenant_id == null
      ? '全平台视角'
      : `聚焦租户 #${view.scope.tenant_id}`
    : `本租户视角${view.scope.tenant_id != null ? ` #${view.scope.tenant_id}` : ''}`;

  const distribution = view.agent_distribution;
  const totalCalls = useMemo(
    () => distribution.reduce((sum, item) => sum + Number(item.value || 0), 0),
    [distribution],
  );
  const hasTrend = view.request_trend.some((p) => p.requests > 0 || p.errors > 0);
  const hasLatency = view.latency_by_hour.some((p) => p.avg > 0);

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
              {isSample ? <Tag color="orange">示例数据</Tag> : null}
              {updatedAt && !isSample ? (
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
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load(days)}>
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
          description={`${error}${isSample ? '（当前展示示例数据）' : ''}`}
          action={
            <Button size="small" onClick={() => void load(days)}>
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
                      <stop offset="0%" stopColor="#1677ff" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#1677ff" stopOpacity={0.02} />
                    </linearGradient>
                    <linearGradient id="dashErrors" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#ff4d4f" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#ff4d4f" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
                  <XAxis dataKey="date" tickLine={false} axisLine={false} fontSize={12} />
                  <YAxis tickLine={false} axisLine={false} fontSize={12} width={56} />
                  <Tooltip />
                  <Legend iconType="circle" />
                  <Area
                    type="monotone"
                    dataKey="requests"
                    name="请求数"
                    stroke="#1677ff"
                    strokeWidth={2}
                    fill="url(#dashRequests)"
                  />
                  <Area
                    type="monotone"
                    dataKey="errors"
                    name="错误数"
                    stroke="#ff4d4f"
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
                      <stop offset="0%" stopColor="#1677ff" stopOpacity={0.9} />
                      <stop offset="100%" stopColor="#69b1ff" stopOpacity={0.55} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
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
            extra={<Typography.Text type="secondary">最新 5 条审计事件</Typography.Text>}
          >
            <Table<ActivityRow>
              size="small"
              rowKey="key"
              pagination={false}
              columns={activityColumns}
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
              <Table<TenantRankRow>
                size="small"
                rowKey="tenant_id"
                pagination={false}
                columns={rankingColumns}
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
