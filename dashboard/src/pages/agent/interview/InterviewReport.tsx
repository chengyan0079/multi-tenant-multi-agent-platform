import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  List,
  Progress,
  Result,
  Row,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from 'antd';

import { getInterviewReport, type InterviewReport as ReportData } from '../../../services/interview';
import { hasScope } from '../../../services/auth';

const formatTime = (value: string | null): string =>
  value ? value.replace('T', ' ').slice(0, 19) : '-';

const STATUS_COLOR: Record<string, string> = {
  in_progress: 'processing',
  finished: 'success',
  failed: 'error',
};
const STATUS_LABEL: Record<string, string> = {
  in_progress: '进行中',
  finished: '已结束',
  failed: '失败',
};

function StringList({ title, items }: { title: string; items: string[] }) {
  return (
    <Card size="small" title={title} style={{ height: '100%' }}>
      {items.length ? (
        <List
          size="small"
          dataSource={items}
          renderItem={(item, index) => (
            <List.Item>
              <Typography.Text>{index + 1}. {item}</Typography.Text>
            </List.Item>
          )}
        />
      ) : (
        <Typography.Text type="secondary">暂无</Typography.Text>
      )}
    </Card>
  );
}

/** 面试报告：五维评分 + 优势/改进/复习建议。 */
export default function InterviewReport() {
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const canView = hasScope('interview:view');

  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState<ReportData | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!canView || !id) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const data = await getInterviewReport(id);
        if (!cancelled) setReport(data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : '报告加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [canView, id]);

  if (!canView) {
    return <Result status="403" title="无权限" subTitle="你没有查看面试报告的权限" />;
  }

  return (
    <Spin spinning={loading}>
      <Card
        title={<Typography.Title level={4} style={{ margin: 0 }}>面试报告</Typography.Title>}
        extra={
          <Button onClick={() => navigate('/agent/interview/results')}>
            返回列表
          </Button>
        }
      >
        {error ? (
          <Result
            status="404"
            title="报告暂不可用"
            subTitle={error}
            extra={
              <Button onClick={() => navigate('/agent/interview/results')}>
                返回面试结果
              </Button>
            }
          />
        ) : !report ? null : (
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <Descriptions column={3} bordered size="small">
              <Descriptions.Item label="会话ID">
                <Typography.Text copyable>{report.session_id}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="目标岗位">{report.target_position}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_COLOR[report.status] ?? 'default'}>
                  {STATUS_LABEL[report.status] ?? report.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="综合得分">
                <Statistic
                  value={report.overall_score ?? 0}
                  suffix="分"
                  valueStyle={{ fontSize: 20 }}
                />
              </Descriptions.Item>
              <Descriptions.Item label="结束时间">
                {formatTime(report.finished_at)}
              </Descriptions.Item>
              <Descriptions.Item label="线程ID">
                <Typography.Text ellipsis>{report.thread_id}</Typography.Text>
              </Descriptions.Item>
            </Descriptions>

            {report.status !== 'finished' ? (
              <Alert
                type="warning"
                showIcon
                message="面试尚未结束"
                description="报告会在面试完成后生成，请稍后刷新。"
              />
            ) : null}

            <div>
              <Divider titlePlacement="left">五维评分</Divider>
              {report.dimensions.length ? (
                <Row gutter={[12, 12]}>
                  {report.dimensions.map((dimension) => (
                    <Col xs={24} md={12} xl={8} key={dimension.dimension}>
                      <Card size="small" title={dimension.dimension} style={{ height: '100%' }}>
                        <Progress
                          percent={Math.max(0, Math.min(100, Number(dimension.score) || 0))}
                          format={(value) => `${value} 分`}
                        />
                        <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
                          {dimension.comment || '暂无评语'}
                        </Typography.Paragraph>
                        <Typography.Text strong>亮点：</Typography.Text>
                        <div>{dimension.highlights?.join('；') || '暂无'}</div>
                        <Typography.Text strong>薄弱点：</Typography.Text>
                        <div>{dimension.weaknesses?.join('；') || '暂无'}</div>
                      </Card>
                    </Col>
                  ))}
                </Row>
              ) : (
                <Typography.Text type="secondary">暂无维度评分</Typography.Text>
              )}
            </div>

            <Row gutter={[12, 12]}>
              <Col xs={24} md={12}>
                <StringList title="优势" items={report.strengths} />
              </Col>
              <Col xs={24} md={12}>
                <StringList title="改进方向" items={report.improvements} />
              </Col>
              <Col xs={24} md={12}>
                <StringList title="推荐复习知识点" items={report.recommended_topics} />
              </Col>
              <Col xs={24} md={12}>
                <Card size="small" title="整体评价" style={{ height: '100%' }}>
                  <Typography.Paragraph>{report.overall_comment || '暂无'}</Typography.Paragraph>
                  <Typography.Text strong>下一步建议：</Typography.Text>
                  <div>{report.next_step_advice || '暂无'}</div>
                </Card>
              </Col>
            </Row>
          </Space>
        )}
      </Card>
    </Spin>
  );
}
