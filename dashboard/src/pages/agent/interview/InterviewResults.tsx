import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  App as AntdApp,
  Button,
  Card,
  Popconfirm,
  Result,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import { ProTable, type ActionType, type ProColumns } from '../../../components/ProTable';

import {
  deleteInterviewSession,
  listInterviewSessions,
  type InterviewSessionItem,
} from '../../../services/interview';
import { hasScope } from '../../../services/auth';

const STATUS_COLOR: Record<string, string> = {
  in_progress: 'processing',
  finished: 'success',
  failed: 'error',
};
const STATUS_LABEL: Record<string, string> = {
  in_progress: '进行中',
  finished: '已结束',
  failed: '失败',
};

const formatTime = (value: string | null): string =>
  value ? value.replace('T', ' ').slice(0, 19) : '-';

/** 面试结果：会话列表，已结束的记录可进入面试报告。 */
export default function InterviewResults() {
  const { message: toast } = AntdApp.useApp();
  const navigate = useNavigate();
  const actionRef = useRef<ActionType>();
  const [status, setStatus] = useState<string | undefined>();

  const canPage = hasScope('interview:page');
  const canView = hasScope('interview:view');
  const canDelete = hasScope('interview:delete');

  const onDelete = async (sessionId: string) => {
    try {
      await deleteInterviewSession(sessionId);
      toast.success('面试会话已删除');
      actionRef.current?.reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '删除失败');
    }
  };

  const columns: ProColumns<InterviewSessionItem>[] = [
    { title: '会话ID', dataIndex: 'session_id', width: 260, ellipsis: true, copyable: true },
    { title: '目标岗位', dataIndex: 'target_position', width: 200, ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (_, row) => (
        <Tag color={STATUS_COLOR[row.status] ?? 'default'}>
          {STATUS_LABEL[row.status] ?? row.status}
        </Tag>
      ),
    },
    {
      title: '综合得分',
      dataIndex: 'overall_score',
      width: 110,
      render: (_, row) =>
        row.overall_score == null ? (
          '-'
        ) : (
          <Typography.Text strong>{row.overall_score}</Typography.Text>
        ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      render: (_, row) => formatTime(row.created_at),
    },
    {
      title: '结束时间',
      dataIndex: 'finished_at',
      width: 180,
      render: (_, row) => formatTime(row.finished_at),
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      valueType: 'option',
      render: (_, row) => (
        <Space size={0}>
          <Button
            type="link"
            size="small"
            disabled={!canView || row.status !== 'finished'}
            onClick={() => navigate(`/agent/interview/results/${row.session_id}`)}
          >
            面试报告
          </Button>
          {canDelete ? (
            <Popconfirm
              title="删除该面试会话？"
              description="软删归档，历史不会立即展示。"
              okText="删除"
              cancelText="取消"
              onConfirm={() => void onDelete(row.session_id)}
            >
              <Button type="link" size="small" danger>
                删除
              </Button>
            </Popconfirm>
          ) : null}
        </Space>
      ),
    },
  ];

  if (!canPage) {
    return <Result status="403" title="无权限" subTitle="你没有查看面试结果的权限" />;
  }

  return (
    <Card title={<Typography.Title level={4} style={{ margin: 0 }}>面试结果</Typography.Title>}>
      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          allowClear
          placeholder="按状态筛选"
          style={{ width: 180 }}
          value={status}
          onChange={(value) => {
            setStatus(value);
            actionRef.current?.reload();
          }}
          options={[
            { value: 'in_progress', label: '进行中' },
            { value: 'finished', label: '已结束' },
            { value: 'failed', label: '失败' },
          ]}
        />
      </Space>
      <ProTable<InterviewSessionItem>
        actionRef={actionRef}
        rowKey="session_id"
        columns={columns}
        search={false}
        options={{ reload: true }}
        request={async (params) => {
          const res = await listInterviewSessions({
            page: params.current ?? 1,
            page_size: params.pageSize ?? 20,
            status,
          });
          return { data: res.items, total: res.total, success: true };
        }}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        scroll={{ x: 'max-content' }}
      />
    </Card>
  );
}
