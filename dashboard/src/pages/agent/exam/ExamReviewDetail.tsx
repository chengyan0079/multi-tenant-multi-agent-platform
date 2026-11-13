import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  App as AntdApp,
  Button,
  Card,
  Col,
  Divider,
  Popconfirm,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  confirmExamReview,
  getExamSubmissionReview,
  type ExamReviewDetail as ExamReviewDetailData,
  type ExamReviewQuestion,
} from '../../../services/exam';

const TYPE_LABEL: Record<string, string> = {
  single_choice: '单选',
  multiple_choice: '多选',
  short_answer: '简答',
};

/** 教师复核页：预评摘要 + 逐题批改 + 薄弱点，确认后发布（HITL 闭环）。 */
export default function ExamReviewDetail() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const [detail, setDetail] = useState<ExamReviewDetailData | null>(null);
  const [loading, setLoading] = useState(false);
  const [publishing, setPublishing] = useState(false);

  useEffect(() => {
    if (!id) return;
    (async () => {
      setLoading(true);
      try {
        setDetail(await getExamSubmissionReview(id));
      } catch (e) {
        message.error((e as Error).message);
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const summary = detail?.pre_review_summary;
  const questions: ExamReviewQuestion[] = summary?.by_question ?? [];
  const weakPoints = (detail?.weak_points ?? []).map((p) => (typeof p === 'string' ? p : p.tag));

  const onPublish = async () => {
    setPublishing(true);
    try {
      await confirmExamReview(id, 'approve');
      message.success('已通过并发布');
      navigate('/agent/exam/reviews');
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setPublishing(false);
    }
  };

  const columns: ColumnsType<ExamReviewQuestion> = [
    { title: '题号', dataIndex: 'question_no', width: 70 },
    { title: '题型', dataIndex: 'question_type', width: 90, render: (v: string) => TYPE_LABEL[v] ?? v },
    { title: '作答', dataIndex: 'student_answer', ellipsis: true },
    { title: '标准答案', dataIndex: 'correct_answer', ellipsis: true },
    { title: 'AI 得分', dataIndex: 'score', width: 90 },
    { title: '满分', dataIndex: 'full_score', width: 80 },
    {
      title: '需复核',
      dataIndex: 'needs_review',
      width: 90,
      render: (v: boolean) => (v ? <Tag color="red">是</Tag> : <Tag color="green">否</Tag>),
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={<Typography.Title level={4} style={{ margin: 0 }}>考试复核</Typography.Title>}
        extra={
          <Space>
            <Button onClick={() => navigate('/agent/exam/reviews')}>返回列表</Button>
            <Popconfirm
              title="确认通过并发布？"
              description="发布后学生即可查看报告"
              onConfirm={onPublish}
              okText="发布"
              cancelText="取消"
            >
              <Button type="primary" loading={publishing}>
                通过并发布
              </Button>
            </Popconfirm>
          </Space>
        }
      >
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} md={6}>
            <Statistic
              title="预评总分"
              value={summary?.total_score ?? 0}
              suffix={`/ ${summary?.full_score ?? 0}`}
            />
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Statistic title="需复核题数" value={summary?.needs_review_count ?? 0} />
          </Col>
        </Row>
        <Typography.Paragraph style={{ marginTop: 16, marginBottom: 0 }}>
          {detail?.weak_points_summary ?? ''}
        </Typography.Paragraph>
      </Card>

      <Card title="逐题批改">
        <Divider style={{ marginTop: 0 }} />
        <Table<ExamReviewQuestion>
          rowKey="question_id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={questions}
          pagination={false}
          scroll={{ x: 'max-content' }}
        />
      </Card>

      <Card title="薄弱点">
        <Space wrap>
          {weakPoints.map((p) => (
            <Tag key={p} color="red">
              {p}
            </Tag>
          ))}
        </Space>
      </Card>
    </Space>
  );
}
