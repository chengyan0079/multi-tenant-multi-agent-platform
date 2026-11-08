import { useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { App as AntdApp, Card, Popconfirm, Result, Tag, Typography } from 'antd';
import { ProTable, type ActionType, type ProColumns } from '../../../components/ProTable';

import { deleteQaSession, listQaSessions, type QaSessionItem } from '../../../services/qa';
import { hasScope } from '../../../services/auth';

const STATUS_COLOR: Record<string, string> = {
  active: 'success',
  archived: 'default',
};

const formatTime = (value: string): string =>
  (value || '').replace('T', ' ').slice(0, 19) || '-';

/** 会话列表：对接 /api/v1/tenant/qa/sessions（qa_session:page / delete）。 */
export default function Sessions() {
  const { message } = AntdApp.useApp();
  const navigate = useNavigate();
  const actionRef = useRef<ActionType>();

  const canPage = hasScope('qa_session:page');
  const canView = hasScope('qa_session:view');
  const canDelete = hasScope('qa_session:delete');

  const columns: ProColumns<QaSessionItem>[] = [
    { title: '会话ID', dataIndex: 'thread_id', width: 240, ellipsis: true, copyable: true },
    { title: '标题', dataIndex: 'title', width: 200, ellipsis: true },
    { title: '会话键', dataIndex: 'session_id', width: 220, ellipsis: true, copyable: true },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_, row) => (
        <Tag color={STATUS_COLOR[row.status] ?? 'default'}>{row.status}</Tag>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (_, row) => formatTime(row.created_at),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 170,
      render: (_, row) => formatTime(row.updated_at),
    },
    {
      title: '操作',
      width: 140,
      valueType: 'option',
      render: (_, row) => [
        canView ? (
          <Typography.Link
            key="view"
            onClick={() => navigate(`/agent/qa/chat?thread_id=${row.thread_id}`)}
          >
            查看
          </Typography.Link>
        ) : null,
        canDelete ? (
          <Popconfirm
            key="delete"
            title="删除该会话？"
            onConfirm={async () => {
              try {
                await deleteQaSession(row.thread_id);
                message.success('已删除');
                actionRef.current?.reload();
              } catch (e) {
                message.error(e instanceof Error ? e.message : '删除失败');
              }
            }}
            okText="删除"
            cancelText="取消"
          >
            <Typography.Link type="danger">删除</Typography.Link>
          </Popconfirm>
        ) : null,
      ],
    },
  ];

  if (!canPage) {
    return <Result status="403" title="无权限" subTitle="你没有查看会话列表的权限" />;
  }

  return (
    <Card title={<Typography.Title level={4} style={{ margin: 0 }}>会话列表</Typography.Title>}>
      <ProTable<QaSessionItem>
        actionRef={actionRef}
        rowKey="thread_id"
        search={false}
        options={{ reload: true }}
        columns={columns}
        request={async (params) => {
          try {
            const res = await listQaSessions({
              page: params.current ?? 1,
              page_size: params.pageSize ?? 20,
            });
            return { data: res.items, total: res.total, success: true };
          } catch (e) {
            message.error(e instanceof Error ? e.message : '会话列表加载失败');
            return { data: [], total: 0, success: false };
          }
        }}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        scroll={{ x: 'max-content' }}
      />
    </Card>
  );
}
