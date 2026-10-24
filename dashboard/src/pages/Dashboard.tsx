import { ArrowUpOutlined } from '@ant-design/icons';
import { Card, Col, Grid, Row, Statistic, Table, Tag, Typography } from 'antd';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import {
  agentDistribution,
  latencyByHour,
  overviewStats,
  recentActivities,
  requestTrend,
} from '../mock/dashboard';

const PIE_COLORS = ['#1677ff', '#52c41a', '#faad14', '#eb2f96', '#722ed1'];

const activityColumns = [
  { title: '时间', dataIndex: 'time', key: 'time' },
  { title: '操作人', dataIndex: 'user', key: 'user' },
  { title: '动作', dataIndex: 'action', key: 'action' },
  { title: '对象', dataIndex: 'target', key: 'target' },
  {
    title: '结果',
    dataIndex: 'result',
    key: 'result',
    render: (value: string) => {
      const color = value === '成功' ? 'green' : value === '失败' ? 'red' : 'orange';
      return <Tag color={color}>{value}</Tag>;
    },
  },
];

/** 首页：监控 / 统计概览（数据为 Mock，布局响应式） */
export default function Dashboard() {
  const screens = Grid.useBreakpoint();
  const isMobile = screens.lg === false;
  const chartHeight = isMobile ? 220 : 280;

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        监控概览
      </Typography.Title>

      <Row gutter={[16, 16]}>
        {overviewStats.map((item) => (
          <Col xs={24} sm={12} lg={6} key={item.title}>
            <Card>
              <Statistic
                title={item.title}
                value={item.value}
                precision={item.precision}
                suffix={item.suffix}
              />
              <Typography.Text type="success" style={{ fontSize: 12 }}>
                <ArrowUpOutlined /> {item.trend}%（较昨日）
              </Typography.Text>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={16}>
          <Card title="近 7 天请求趋势">
            <ResponsiveContainer width="100%" height={chartHeight}>
              <LineChart data={requestTrend}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="requests" name="请求数" stroke="#1677ff" />
                <Line type="monotone" dataKey="errors" name="错误数" stroke="#ff4d4f" />
              </LineChart>
            </ResponsiveContainer>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="智能体调用占比">
            <ResponsiveContainer width="100%" height={chartHeight}>
              <PieChart>
                <Pie data={agentDistribution} dataKey="value" nameKey="name" outerRadius={isMobile ? 70 : 90} label>
                  {agentDistribution.map((_, index) => (
                    <Cell key={index} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="平均响应耗时（ms）">
            <ResponsiveContainer width="100%" height={chartHeight - 40}>
              <BarChart data={latencyByHour}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="hour" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="avg" name="平均耗时" fill="#1677ff" />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="最近活动">
            <Table
              size="small"
              pagination={false}
              columns={activityColumns}
              dataSource={recentActivities}
              scroll={{ x: 420 }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
