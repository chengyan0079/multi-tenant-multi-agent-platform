import { useCallback, useRef } from 'react';
import { Tag, Typography } from 'antd';

import { ProTable, type ProColumns } from '../components/ProTable';
import { listGraphStates, type GraphStateItem } from '../services/graphStates';

export default function GraphStates() {
  const actionRef = useRef<any>();

  const request = useCallback(async (params: any) => {
    const res = await listGraphStates({
      thread_id: params.thread_id || undefined,
      page: params.current ?? 1,
      page_size: params.pageSize ?? 20,
    });
    return { data: res?.items ?? [], success: true, total: res?.total ?? 0 };
  }, []);

  const columns: ProColumns<GraphStateItem>[] = [
    {
      title: 'thread_id',
      dataIndex: 'thread_id',
      width: 320,
      ellipsis: true,
      render: (_: unknown, row: GraphStateItem) => (
        <Typography.Text copyable>{row.thread_id}</Typography.Text>
      ),
    },
    {
      title: 'checkpoint_id',
      dataIndex: 'checkpoint_id',
      width: 300,
      ellipsis: true,
      search: false,
    },
    {
      title: 'agent_type',
      key: 'agent_type',
      width: 120,
      search: false,
      render: (_: unknown, row: GraphStateItem) =>
        (row.metadata?.agent_type as string) || '-',
    },
    {
      title: 'trace_id',
      key: 'trace_id',
      width: 220,
      ellipsis: true,
      search: false,
      render: (_: unknown, row: GraphStateItem) => (row.metadata?.trace_id as string) || '-',
    },
    { title: 'namespace', dataIndex: 'checkpoint_ns', width: 120, search: false },
    {
      title: '类型',
      dataIndex: 'type',
      width: 100,
      search: false,
      render: (_: unknown, row: GraphStateItem) => <Tag>{row.type}</Tag>,
    },
  ];

  return (
    <ProTable<GraphStateItem>
      headerTitle="图状态列表（checkpoints）"
      actionRef={actionRef}
      rowKey={(r) => `${r.thread_id}:${r.checkpoint_id}:${r.checkpoint_ns}`}
      columns={columns}
      request={request}
      search={{ labelWidth: 'auto' }}
      options={{ fullScreen: true, setting: true, density: true, reload: true }}
      scroll={{ x: 'max-content' }}
      pagination={{ pageSize: 20, showSizeChanger: true }}
    />
  );
}
