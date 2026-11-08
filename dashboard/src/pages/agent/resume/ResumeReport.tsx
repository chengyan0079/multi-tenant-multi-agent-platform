import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Progress,
  Result,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate, useParams } from 'react-router-dom';

import {
  getReview,
  type DimensionScore,
  type IssueItem,
  type ResumeDetail,
} from '../../../services/resume';
import { hasScope } from '../../../services/auth';

const STATUS_LABEL: Record<string, string> = {
  pending: '待处理',
  processing: '处理中',
  done: '已完成',
  failed: '失败',
};

const PRIORITY_COLOR: Record<string, string> = {
  high: 'red',
  medium: 'orange',
  low: 'default',
};

const formatTime = (value: string | null): string =>
  value ? value.replace('T', ' ').slice(0, 19) : '-';

const weightPercent = (weight: number): number =>
  Math.round(weight <= 1 ? weight * 100 : weight);

/** 简历分析报告页：维度评分 + 问题诊断 + 整体评价。 */
export default function ResumeReport() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const canView = hasScope('resume:view');

  const [detail, setDetail] = useState<ResumeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const res = await getReview(id);
      setDetail(res);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '评审结果加载失败');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (detail?.status !== 'processing') return undefined;
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [detail?.status, load]);

  if (!canView) {
    return <Result status="403" title="无权限" subTitle="你没有查看简历报告的权限" />;
  }

  if (loading && !detail) {
    return (
      <Card>
        <Spin tip="加载评审结果..." />
      </Card>
    );
  }

  if (error && !detail) {
    return (
      <Result
        status="404"
        title="评审记录不存在或加载失败"
        subTitle={error}
        extra={<Button onClick={() => navigate('/agent/resume/analysis')}>返回列表</Button>}
      />
    );
  }

  if (!detail) {
    return <Empty description="暂无评审数据" />;
  }

  const dimensions = detail.dimension_scores ?? [];
  const issues = detail.issues ?? [];
  const summary = detail.summary;

  const issueColumns: ColumnsType<IssueItem> = [
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 90,
      render: (value: string) => (
        <Tag color={PRIORITY_COLOR[value] ?? 'default'}>{value || '-'}</Tag>
      ),
    },
    { title: '维度', dataIndex: 'dimension', width: 110 },
    { title: '问题描述', dataIndex: 'description' },
    { title: '位置', dataIndex: 'location', width: 220, ellipsis: true },
    { title: '修改建议', dataIndex: 'suggestion', width: 320, ellipsis: true },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={<Typography.Title level={4} style={{ margin: 0 }}>简历分析报告</Typography.Title>}
        extra={<Button onClick={() => navigate('/agent/resume/analysis')}>返回列表</Button>}
      >
        {detail.status === 'processing' ? (
          <Alert
            type="info"
            showIcon
            message="评审处理中"
            description="后台正在解析简历并生成六维度评分，页面会自动刷新。"
          />
        ) : null}
        {detail.status === 'failed' ? (
          <Alert
            type="error"
            showIcon
            message="评审失败"
            description={detail.error_msg || '未知错误，请重新上传简历'}
          />
        ) : null}

        <Row gutter={[16, 16]} style={{ marginTop: detail.status === 'done' ? 0 : 16 }}>
          <Col xs={24} sm={12} md={6}>
            <Card size="small">
              <Statistic
                title="综合得分"
                value={detail.weighted_score ?? 0}
                precision={1}
                suffix="/ 100"
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card size="small">
              <Statistic title="评审ID" value={detail.review_id} />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card size="small">
              <Statistic title="状态" value={STATUS_LABEL[detail.status] ?? detail.status} />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card size="small">
              <Statistic title="创建时间" value={formatTime(detail.created_at)} />
            </Card>
          </Col>
        </Row>
      </Card>

      {dimensions.length > 0 ? (
        <Row gutter={[16, 16]}>
          {dimensions.map((d: DimensionScore) => (
            <Col xs={24} sm={12} xl={8} key={d.dimension}>
              <Card
                size="small"
                title={
                  <Space>
                    <span>{d.dimension || '未命名维度'}</span>
                    <Tag color="blue">权重 {weightPercent(d.weight)}%</Tag>
                  </Space>
                }
              >
                <Statistic value={d.score} suffix="/ 100" />
                <Progress percent={d.score} showInfo={false} />

                <Divider>存在的主要问题</Divider>
                {d.issues?.length ? (
                  <ul style={{ paddingLeft: 18, margin: 0 }}>
                    {d.issues.map((p, i) => (
                      <li key={i} style={{ marginBottom: 6 }}>
                        {p}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <Typography.Text type="secondary">暂无</Typography.Text>
                )}

                <Divider>改进建议</Divider>
                {d.suggestions?.length ? (
                  <ul style={{ paddingLeft: 18, margin: 0 }}>
                    {d.suggestions.map((s, i) => (
                      <li key={i} style={{ marginBottom: 6 }}>
                        {s}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <Typography.Text type="secondary">暂无</Typography.Text>
                )}
              </Card>
            </Col>
          ))}
        </Row>
      ) : (
        <Card size="small" title="维度评分">
          <Empty description={detail.status === 'processing' ? '评审中，请稍候' : '暂无维度评分'} />
        </Card>
      )}

      <Card title="问题诊断">
        {issues.length > 0 ? (
          <Table<IssueItem>
            rowKey={(_, index) => String(index)}
            size="small"
            columns={issueColumns}
            dataSource={issues}
            pagination={false}
            scroll={{ x: 'max-content' }}
          />
        ) : (
          <Empty description="暂无问题诊断" />
        )}
      </Card>

      <Card title="整体评价">
        {summary ? (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {summary.overall_comment ? (
              <Typography.Paragraph style={{ marginBottom: 0 }}>
                {summary.overall_comment}
              </Typography.Paragraph>
            ) : null}
            {summary.fit_assessment ? (
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                岗位匹配度：{summary.fit_assessment}
              </Typography.Paragraph>
            ) : null}

            <Divider style={{ margin: '4px 0' }}>核心亮点</Divider>
            {summary.highlights?.length ? (
              <ul style={{ paddingLeft: 18, margin: 0 }}>
                {summary.highlights.map((item, i) => (
                  <li key={i} style={{ marginBottom: 4 }}>
                    {item}
                  </li>
                ))}
              </ul>
            ) : (
              <Typography.Text type="secondary">暂无</Typography.Text>
            )}

            <Divider style={{ margin: '4px 0' }}>核心改进方向</Divider>
            {summary.core_improvements?.length ? (
              <ul style={{ paddingLeft: 18, margin: 0 }}>
                {summary.core_improvements.map((item, i) => (
                  <li key={i} style={{ marginBottom: 4 }}>
                    {item}
                  </li>
                ))}
              </ul>
            ) : (
              <Typography.Text type="secondary">暂无</Typography.Text>
            )}
          </Space>
        ) : (
          <Empty description="暂无整体评价" />
        )}
      </Card>
    </Space>
  );
}
