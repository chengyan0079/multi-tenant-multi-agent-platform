import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Tag, Typography } from 'antd';
import { ProTable, type ProColumns } from '../../../components/ProTable';
import { listPendingExamReviews, type ExamPendingReviewItem } from '../../../services/exam';

/** 教师待复核列表：本租户 pending_review 提交，点「复核」进入复核页。 */
export default function ExamReview() {
  const navigate = useNavigate();
  const [data, setData] = useState<ExamPendingReviewItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res = await listPendingExamReviews();
        setData(res.items ?? []);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const columns: ProColumns<ExamPendingReviewItem>[] = [
    { title: '提交ID', dataIndex: 'submission_id', width: 130, ellipsis: true, copyable: true },
    { title: '学生', dataIndex: 'student_name', width: 120 },
    { title: '试卷', dataIndex: 'exam_title', ellipsis: true },
    {
      title: '预评分',
      key: 'score',
      width: 110,
      render: (_, row) => `${row.pre_review.total_score} / ${row.pre_review.full_score}`,
    },
    {
      title: '需复核',
      key: 'needs',
      width: 90,
      render: (_, row) => <Tag color="warning">{row.pre_review.needs_review_count} 题</Tag>,
    },
    {
      title: '提交时间',
      dataIndex: 'submitted_at',
      width: 170,
      render: (_, row) => row.submitted_at ?? '-',
    },
    {
      title: '操作',
      width: 100,
      valueType: 'option',
      render: (_, row) => (
        <Button
          type="link"
          size="small"
          onClick={() => navigate(`/agent/exam/reviews/${row.submission_id}`)}
        >
          复核
        </Button>
      ),
    },
  ];

  return (
    <Card title={<Typography.Title level={4} style={{ margin: 0 }}>考试待复核</Typography.Title>}>
      <ProTable<ExamPendingReviewItem>
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
