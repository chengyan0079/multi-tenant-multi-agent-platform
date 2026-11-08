import { useNavigate, useParams } from 'react-router-dom';
import {
  Button,
  Card,
  Col,
  Divider,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';

interface KnowledgeStat {
  tag: string;
  accuracy: number;
}

interface ReviewItem {
  questionNo: number;
  questionType: string;
  knowledgeTag: string;
  studentAnswer: string;
  aiScore: number;
  finalScore: number;
  needsReview: boolean;
}

interface ExamReportData {
  submissionId: string;
  examTitle: string;
  userId: number;
  status: string;
  finalScore: number;
  knowledgeStats: KnowledgeStat[];
  weakPoints: string[];
  weakSummary: string;
  reviews: ReviewItem[];
  submittedAt: string;
}

const REPORTS: Record<string, ExamReportData> = {
  'sub-1001-01': {
    submissionId: 'sub-1001-01',
    examTitle: 'Java 后端工程师-基础能力测评',
    userId: 1001,
    status: 'published',
    finalScore: 88,
    knowledgeStats: [
      { tag: '集合框架', accuracy: 92 },
      { tag: '并发编程', accuracy: 78 },
      { tag: 'JVM', accuracy: 85 },
      { tag: '数据库', accuracy: 95 },
    ],
    weakPoints: ['并发编程', 'JVM 内存模型'],
    weakSummary:
      '整体基础扎实，集合与数据库表现最好；并发编程与 JVM 相对薄弱，建议重点复习线程池参数、锁机制与内存模型。',
    reviews: [
      {
        questionNo: 1,
        questionType: 'single_choice',
        knowledgeTag: '集合框架',
        studentAnswer: 'B',
        aiScore: 10,
        finalScore: 10,
        needsReview: false,
      },
      {
        questionNo: 2,
        questionType: 'single_choice',
        knowledgeTag: '并发编程',
        studentAnswer: 'C',
        aiScore: 0,
        finalScore: 0,
        needsReview: true,
      },
      {
        questionNo: 3,
        questionType: 'short_answer',
        knowledgeTag: 'JVM',
        studentAnswer: '堆是线程共享、存放对象实例的区域……',
        aiScore: 8,
        finalScore: 9,
        needsReview: false,
      },
      {
        questionNo: 4,
        questionType: 'short_answer',
        knowledgeTag: '数据库',
        studentAnswer: '索引通过 B+ 树加速查询，避免全表扫描……',
        aiScore: 10,
        finalScore: 10,
        needsReview: false,
      },
    ],
    submittedAt: '2026-11-05 09:30:12',
  },
  'sub-2001-01': {
    submissionId: 'sub-2001-01',
    examTitle: '前端工程师-进阶测评',
    userId: 2001,
    status: 'reviewed',
    finalScore: 76,
    knowledgeStats: [
      { tag: 'react', accuracy: 82 },
      { tag: 'css', accuracy: 70 },
      { tag: '工程化', accuracy: 74 },
    ],
    weakPoints: ['css 布局', '构建优化'],
    weakSummary: 'react 掌握较好，css 布局与构建优化需要加强，建议补充 flex/grid 与打包体积优化实践。',
    reviews: [
      {
        questionNo: 1,
        questionType: 'single_choice',
        knowledgeTag: 'react',
        studentAnswer: 'A',
        aiScore: 10,
        finalScore: 10,
        needsReview: false,
      },
      {
        questionNo: 2,
        questionType: 'single_choice',
        knowledgeTag: 'css',
        studentAnswer: 'D',
        aiScore: 0,
        finalScore: 0,
        needsReview: true,
      },
      {
        questionNo: 3,
        questionType: 'short_answer',
        knowledgeTag: '工程化',
        studentAnswer: '通过 code splitting 与 tree shaking 减小体积……',
        aiScore: 8,
        finalScore: 8,
        needsReview: false,
      },
    ],
    submittedAt: '2026-11-04 17:05:40',
  },
};

const DEFAULT_REPORT = REPORTS['sub-1001-01'];
const STATUS_LABEL: Record<string, string> = {
  submitted: '已提交',
  ai_processing: 'AI 批改中',
  pending_review: '待复核',
  reviewed: '已复核',
  published: '已发布',
};

/** 考试结果报告页：综合得分 + 知识点掌握 + 薄弱点 + 批改明细。 */
export default function ExamReport() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const report = REPORTS[id] ?? DEFAULT_REPORT;

  const reviewColumns: ColumnsType<ReviewItem> = [
    { title: '题号', dataIndex: 'questionNo', width: 70 },
    { title: '题型', dataIndex: 'questionType', width: 120 },
    { title: '知识点', dataIndex: 'knowledgeTag', width: 110, render: (v: string) => <Tag>{v}</Tag> },
    { title: '作答', dataIndex: 'studentAnswer', ellipsis: true },
    { title: 'AI 评分', dataIndex: 'aiScore', width: 90 },
    { title: '最终得分', dataIndex: 'finalScore', width: 90 },
    {
      title: '需复核',
      dataIndex: 'needsReview',
      width: 90,
      render: (v: boolean) => (v ? <Tag color="red">是</Tag> : <Tag color="green">否</Tag>),
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={<Typography.Title level={4} style={{ margin: 0 }}>考试结果报告</Typography.Title>}
        extra={<Button onClick={() => navigate('/agent/exam/results')}>返回列表</Button>}
      >
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} md={6}>
            <Card size="small">
              <Statistic title="综合得分" value={report.finalScore} suffix="/ 100" />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card size="small">
              <Statistic title="考生" value={report.userId} />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card size="small">
              <Statistic title="提交时间" value={report.submittedAt} />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card size="small">
              <Statistic title="状态" value={STATUS_LABEL[report.status] ?? report.status} />
            </Card>
          </Col>
        </Row>
        <Typography.Paragraph style={{ marginTop: 16, marginBottom: 0 }}>
          {report.examTitle}
        </Typography.Paragraph>
      </Card>

      <Card title="知识点掌握">
        <Row gutter={[16, 16]}>
          {report.knowledgeStats.map((k) => (
            <Col xs={24} sm={12} md={8} lg={6} key={k.tag}>
              <Card size="small">
                <Statistic title={k.tag} value={k.accuracy} suffix="%" />
                <Progress percent={k.accuracy} size="small" showInfo={false} />
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      <Card title="薄弱点">
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap>
            {report.weakPoints.map((p) => (
              <Tag key={p} color="red">
                {p}
              </Tag>
            ))}
          </Space>
          <Typography.Paragraph style={{ marginBottom: 0 }}>
            {report.weakSummary}
          </Typography.Paragraph>
        </Space>
      </Card>

      <Card title="批改明细">
        <Divider style={{ marginTop: 0 }} />
        <Table<ReviewItem>
          rowKey="questionNo"
          size="small"
          columns={reviewColumns}
          dataSource={report.reviews}
          pagination={false}
          scroll={{ x: 'max-content' }}
        />
      </Card>
    </Space>
  );
}
