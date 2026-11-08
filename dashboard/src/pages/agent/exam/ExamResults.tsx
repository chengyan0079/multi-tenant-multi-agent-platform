import { useNavigate } from 'react-router-dom';
import { Button, Card, Tag, Typography } from 'antd';
import { ProTable, type ProColumns } from '../../../components/ProTable';

// 列表字段参考 agent_exam_submissions + agent_exams（详情在报告页展示）
interface ExamSubmissionRow {
  submissionId: string;
  examTitle: string;
  userId: number;
  tenantId: number;
  source: string;
  status: string;
  finalScore: number | null;
  submittedAt: string;
}

const MOCK_ROWS: ExamSubmissionRow[] = [
  {
    submissionId: 'sub-1001-01',
    examTitle: 'Java 后端工程师-基础能力测评',
    userId: 1001,
    tenantId: 100,
    source: 'online',
    status: 'published',
    finalScore: 88,
    submittedAt: '2026-11-05 09:30:12',
  },
  {
    submissionId: 'sub-2001-01',
    examTitle: '前端工程师-进阶测评',
    userId: 2001,
    tenantId: 300,
    source: 'word',
    status: 'reviewed',
    finalScore: 76,
    submittedAt: '2026-11-04 17:05:40',
  },
  {
    submissionId: 'sub-3001-01',
    examTitle: 'Java 后端工程师-基础能力测评',
    userId: 3001,
    tenantId: 100,
    source: 'online',
    status: 'ai_processing',
    finalScore: null,
    submittedAt: '2026-11-05 10:40:00',
  },
];

const STATUS_COLOR: Record<string, string> = {
  submitted: 'default',
  ai_processing: 'processing',
  pending_review: 'warning',
  reviewed: 'blue',
  published: 'success',
};
const STATUS_LABEL: Record<string, string> = {
  submitted: '已提交',
  ai_processing: 'AI 批改中',
  pending_review: '待复核',
  reviewed: '已复核',
  published: '已发布',
};

/** 考试结果（mock）：列表，点击「报告」进入报告页。 */
export default function ExamResults() {
  const navigate = useNavigate();

  const columns: ProColumns<ExamSubmissionRow>[] = [
    { title: '提交ID', dataIndex: 'submissionId', width: 130, ellipsis: true, copyable: true },
    { title: '试卷', dataIndex: 'examTitle', ellipsis: true },
    { title: '考生', dataIndex: 'userId', width: 80 },
    { title: '来源', dataIndex: 'source', width: 90 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (_, row) => (
        <Tag color={STATUS_COLOR[row.status] ?? 'default'}>
          {STATUS_LABEL[row.status] ?? row.status}
        </Tag>
      ),
    },
    {
      title: '得分',
      dataIndex: 'finalScore',
      width: 90,
      render: (_, row) =>
        row.finalScore == null ? '-' : <Typography.Text strong>{row.finalScore}</Typography.Text>,
    },
    { title: '提交时间', dataIndex: 'submittedAt', width: 170 },
    {
      title: '操作',
      width: 90,
      valueType: 'option',
      render: (_, row) => (
        <Button
          type="link"
          size="small"
          onClick={() => navigate(`/agent/exam/results/${row.submissionId}`)}
        >
          报告
        </Button>
      ),
    },
  ];

  return (
    <Card title={<Typography.Title level={4} style={{ margin: 0 }}>考试结果</Typography.Title>}>
      <ProTable<ExamSubmissionRow>
        rowKey="submissionId"
        search={false}
        options={false}
        columns={columns}
        dataSource={MOCK_ROWS}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        scroll={{ x: 'max-content' }}
      />
    </Card>
  );
}
