import { useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import {
  Button,
  Card,
  Col,
  Divider,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  getMyExamSubmission,
  type ExamReviewQuestion,
  type ExamSubmissionDetail,
} from '../../../services/exam';

const STATUS_LABEL: Record<string, string> = {
  submitted: '已提交',
  ai_processing: 'AI 批改中',
  pending_review: '待复核',
  reviewed: '已复核',
  published: '已发布',
};

const TYPE_LABEL: Record<string, string> = {
  single_choice: '单选',
  multiple_choice: '多选',
  short_answer: '简答',
};

/** 考试结果报告页：综合得分 + 逐题批改明细 + 薄弱点。 */
export default function ExamReport() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { examTitle = '', submittedAt = '' } =
    (location.state as { examTitle?: string; submittedAt?: string } | null) ?? {};

  const [detail, setDetail] = useState<ExamSubmissionDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!id) return;
    (async () => {
      setLoading(true);
      try {
        setDetail(await getMyExamSubmission(id));
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  const summary = detail?.pre_review_summary;
  const questions: ExamReviewQuestion[] = summary?.by_question ?? [];
  const weakPoints: string[] = (detail?.weak_points ?? []).map((p) =>
    typeof p === 'string' ? p : p.tag,
  );
  const weakSummary: string = detail?.weak_points_summary ?? '';

  const reviewColumns: ColumnsType<ExamReviewQuestion> = [
    { title: '题号', dataIndex: 'question_no', width: 70 },
    { title: '题型', dataIndex: 'question_type', width: 90, render: (v: string) => TYPE_LABEL[v] ?? v },
    { title: '作答', dataIndex: 'student_answer', ellipsis: true },
    { title: '参考答案', dataIndex: 'correct_answer', ellipsis: true },
    { title: 'AI 评分', dataIndex: 'score', width: 90 },
    { title: '最终得分', dataIndex: 'final_score', width: 90 },
    {
      title: '需复核',
      dataIndex: 'needs_review',
      width: 90,
      render: (v: boolean) => (v ? <Tag color="red">是</Tag> : <Tag color="green">否</Tag>),
    },
  ];

  const notPublished = !detail || (detail.status !== 'published' && !summary);

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={<Typography.Title level={4} style={{ margin: 0 }}>考试结果报告</Typography.Title>}
        extra={<Button onClick={() => navigate('/agent/exam/results')}>返回列表</Button>}
      >
        {notPublished ? (
          <Typography.Paragraph style={{ marginBottom: 0 }}>
            {STATUS_LABEL[detail?.status ?? ''] ?? detail?.status ?? '加载中'}…该提交暂未发布，发布后可查看完整报告。
          </Typography.Paragraph>
        ) : (
          <Row gutter={[16, 16]}>
            <Col xs={24} sm={12} md={6}>
              <Card size="small">
                <Statistic
                  title="综合得分"
                  value={summary!.total_score}
                  suffix={`/ ${summary!.full_score}`}
                />
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card size="small">
                <Statistic
                  title="得分率"
                  value={Math.round((summary!.score_rate ?? 0) * 100)}
                  suffix="%"
                />
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card size="small">
                <Statistic title="提交时间" value={submittedAt || '-'} />
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card size="small">
                <Statistic title="状态" value={STATUS_LABEL[detail!.status] ?? detail!.status} />
              </Card>
            </Col>
          </Row>
        )}
        {examTitle && (
          <Typography.Paragraph style={{ marginTop: 16, marginBottom: 0 }}>{examTitle}</Typography.Paragraph>
        )}
      </Card>

      {summary && (
        <>
          <Card title="批改明细">
            <Divider style={{ marginTop: 0 }} />
            <Table<ExamReviewQuestion>
              rowKey="question_id"
              size="small"
              loading={loading}
              columns={reviewColumns}
              dataSource={questions}
              pagination={false}
              scroll={{ x: 'max-content' }}
            />
          </Card>

          <Card title="薄弱点">
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Space wrap>
                {weakPoints.map((p) => (
                  <Tag key={p} color="red">
                    {p}
                  </Tag>
                ))}
              </Space>
              <Typography.Paragraph style={{ marginBottom: 0 }}>{weakSummary}</Typography.Paragraph>
            </Space>
          </Card>
        </>
      )}
    </Space>
  );
}
