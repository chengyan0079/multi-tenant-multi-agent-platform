import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Tag, Typography } from 'antd';
import { ProTable, type ProColumns } from '../../../components/ProTable';
import { hasScope } from '../../../services/auth';
import { listMyExamSubmissions, type ExamSubmissionItem } from '../../../services/exam';

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

/** 考试结果：当前用户的提交列表，点击「报告」进入报告页。 */
export default function ExamResults() {
  const navigate = useNavigate();
  const [data, setData] = useState<ExamSubmissionItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res = await listMyExamSubmissions();
        setData(res.items ?? []);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const columns: ProColumns<ExamSubmissionItem>[] = [
    { title: '提交ID', dataIndex: 'submission_id', width: 130, ellipsis: true, copyable: true },
    { title: '试卷', dataIndex: 'exam_title', ellipsis: true },
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
      title: '提交时间',
      dataIndex: 'submitted_at',
      width: 170,
      render: (_, row) => row.submitted_at ?? '-',
    },
    {
      title: '操作',
      width: 90,
      valueType: 'option',
      render: (_, row) => (
        <Button
          type="link"
          size="small"
          onClick={() =>
            navigate(`/agent/exam/results/${row.submission_id}`, {
              state: { examTitle: row.exam_title, submittedAt: row.submitted_at },
            })
          }
        >
          报告
        </Button>
      ),
    },
  ];

  return (
    <Card
      title={<Typography.Title level={4} style={{ margin: 0 }}>考试结果</Typography.Title>}
      extra={
        hasScope('exam:review') ? (
          <Button onClick={() => navigate('/agent/exam/reviews')}>待复核</Button>
        ) : null
      }
    >
      <ProTable<ExamSubmissionItem>
        rowKey="submission_id"
        search={false}
        options={false}
        loading={loading}
        columns={columns}
        dataSource={data}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        scroll={{ x: 'max-content' }}
      />
    </Card>
  );
}
