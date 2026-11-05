import { useCallback, useEffect, useState } from 'react';
import { App as AntdApp, Button, Popconfirm, Space, Tag, Typography } from 'antd';
import { ProTable, type ProColumns } from '@ant-design/pro-components';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';

import { deleteReview, listResumes, type ResumeItem } from '../../services/resume';
import { hasScope } from '../../services/auth';

const STATUS_META: Record<string, { text: string; color: string }> = {
  processing: { text: '评审中', color: 'processing' },
  completed: { text: '已完成', color: 'success' },
  failed: { text: '失败', color: 'error' },
};

/** 评审列表页（resume:page）：列出当前用户的评审单，行内「评审查看/删除」按 scope 门控。 */
export default function ResumeList() {
  const { message } = AntdApp.useApp();
  const navigate = useNavigate();
  const [data, setData] = useState<ResumeItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listResumes({ page, page_size: pageSize });
      setData(res.items);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleDelete = async (id: string) => {
    try {
      await deleteReview(id);
      message.success('已删除');
      void load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const columns: ProColumns<ResumeItem>[] = [
    {
      title: '评审单号',
      dataIndex: 'review_id',
      key: 'review_id',
      ellipsis: true,
      render: (_, r) => (
        <Typography.Text copyable={{ text: r.review_id }}>{r.review_id.slice(0, 8)}…</Typography.Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (_, r) => {
        const meta = STATUS_META[r.status] ?? STATUS_META.processing;
        return <Tag color={meta.color}>{meta.text}</Tag>;
      },
    },
    {
      title: '综合得分',
      dataIndex: 'weighted_score',
      key: 'weighted_score',
      width: 110,
      render: (_, r) => (r.weighted_score == null ? '-' : r.weighted_score.toFixed(1)),
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (_, r) => (r.created_at ? dayjs(r.created_at).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_, r) => (
        <Space>
          {hasScope('resume:view') && (
            <Button type="link" onClick={() => navigate(`/resume/view/${r.review_id}`)}>
              评审查看
            </Button>
          )}
          {hasScope('resume:delete') && (
            <Popconfirm
              title="确认删除该评审记录？"
              okText="删除"
              cancelText="取消"
              onConfirm={() => handleDelete(r.review_id)}
            >
              <Button type="link" danger>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        评审列表
      </Typography.Title>
      <Space style={{ marginBottom: 16 }} wrap>
        {hasScope('resume:upload') && (
          <Button type="primary" onClick={() => navigate('/resume/upload')}>
            简历上传
          </Button>
        )}
        <Button onClick={() => void load()}>刷新</Button>
        <Typography.Text type="secondary">共 {total} 条评审</Typography.Text>
      </Space>
      <ProTable<ResumeItem>
        search={false}
        options={{ fullScreen: true, setting: true, density: true, reload: false }}
        rowKey="review_id"
        loading={loading}
        columns={columns}
        dataSource={data}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: false,
          onChange: (next, size) => {
            setPage(next);
            setPageSize(size);
          },
        }}
        scroll={{ x: 'max-content' }}
      />
    </div>
  );
}
