import { useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Popconfirm, Space, Tag, Typography, message } from 'antd';
import { ProTable, type ProColumns } from '../../components/ProTable';
import { deleteAdminSession, listAdminSessions, type SessionItem } from '../../services/unified';

const AGENT_ENUM: Record<string, { text: string }> = {
  qa: { text: 'qa' },
  db_review: { text: 'db_review' },
  db_release: { text: 'db_release' },
};

const STATUS_ENUM: Record<string, { text: string }> = {
  active: { text: 'active' },
  archived: { text: 'archived' },
  deleted: { text: 'deleted' },
};

export default function UnifiedSessionList() {
  const navigate = useNavigate();
  const actionRef = useRef<any>();

  const request = useCallback(async (params: any) => {
    const res = await listAdminSessions({
      page: params.current ?? 1,
      page_size: params.pageSize ?? 20,
      status: params.status || undefined,
      thread_id: params.thread_id || undefined,
      agent_type: params.agent_type || undefined,
    });
    return { data: res?.items ?? [], success: true, total: res?.total ?? 0 };
  }, []);

  const onDelete = async (s: SessionItem) => {
    try {
      await deleteAdminSession(s.thread_id);
      message.success('已删除');
      actionRef.current?.reload?.();
    } catch {
      message.error('删除失败');
    }
  };

  const columns: ProColumns<SessionItem>[] = [
    {
      title: 'thread_id',
      dataIndex: 'thread_id',
      width: 320,
      ellipsis: true,
      copyable: true,
      render: (_: unknown, s: SessionItem) => (
        <Typography.Text copyable>{s.thread_id}</Typography.Text>
      ),
    },
    {
      title: '标题',
      dataIndex: 'title',
      width: 220,
      ellipsis: true,
      search: false,
      render: (_: unknown, s: SessionItem) => s.title || '未命名会话',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      valueEnum: STATUS_ENUM,
      render: (_: unknown, s: SessionItem) => <Tag>{s.status || '-'}</Tag>,
    },
    {
      title: 'Agent',
      dataIndex: 'agent_type',
      width: 140,
      valueEnum: AGENT_ENUM,
      render: (_: unknown, s: SessionItem) =>
        s.agent_type ? <Tag color="blue">{s.agent_type}</Tag> : '-',
    },
    {
      title: '会话键',
      dataIndex: 'session_id',
      width: 240,
      ellipsis: true,
      search: false,
    },
    {
      title: '轮数',
      dataIndex: 'turn_count',
      width: 90,
      search: false,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 180,
      search: false,
    },
    {
      title: '操作',
      width: 160,
      search: false,
      render: (_: unknown, s: SessionItem) => (
        <Space>
          <Button size="small" onClick={() => navigate(`/consultation/sessions/${s.thread_id}`)}>
            查看
          </Button>
          <Popconfirm
            title="删除该会话？"
            description="仅删除会话条目，问答历史与测评保留"
            okText="删除"
            cancelText="取消"
            onConfirm={() => onDelete(s)}
          >
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <ProTable<SessionItem>
      headerTitle="会话管理（本租户会话）"
      actionRef={actionRef}
      rowKey={(r) => r.thread_id}
      columns={columns}
      request={request}
      search={{ labelWidth: 'auto' }}
      options={{ fullScreen: true, setting: true, density: true, reload: true }}
      scroll={{ x: 'max-content' }}
      pagination={{ pageSize: 20, showSizeChanger: true }}
    />
  );
}
