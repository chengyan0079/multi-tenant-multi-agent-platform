import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Popconfirm, Space, Table, Tag, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { deleteAdminSession, listAdminSessions, type SessionItem } from '../../services/unified';

export default function UnifiedSessionList() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [rows, setRows] = useState<SessionItem[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await listAdminSessions({ page: 1, page_size: 50 });
      setRows(r.items);
    } catch {
      message.error('加载会话列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onDelete = async (s: SessionItem) => {
    try {
      await deleteAdminSession(s.thread_id);
      message.success('已删除');
      await load();
    } catch {
      message.error('删除失败');
    }
  };

  const columns: ColumnsType<SessionItem> = [
    { title: '标题', dataIndex: 'title', render: (v: string) => v || '未命名会话' },
    { title: '会话键', dataIndex: 'session_id' },
    {
      title: '状态',
      dataIndex: 'status',
      render: (v: string) => <Tag>{v}</Tag>,
    },
    { title: 'Agent', dataIndex: 'agent_type', render: (v: string) => (v ? <Tag color="blue">{v}</Tag> : '-') },
    { title: '轮数', dataIndex: 'turn_count' },
    { title: '更新时间', dataIndex: 'updated_at' },
    {
      title: '操作',
      render: (_, s) => (
        <Space>
          <Button size="small" onClick={() => navigate(`/consultation/sessions/${s.thread_id}`)}>
            查看
          </Button>
          <Popconfirm title="删除该会话？" okText="删除" cancelText="取消" onConfirm={() => onDelete(s)}>
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card title="会话管理（本租户全部会话）">
      <Table
        rowKey="thread_id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
      />
    </Card>
  );
}
