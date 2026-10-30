import { useCallback, useEffect, useState } from 'react';
import { Alert, App as AntdApp, Button, Descriptions, Drawer, Popconfirm, Select, Space, Tag, Typography } from 'antd';
import { ProTable, type ProColumns } from '@ant-design/pro-components';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import { getOutbox, listMessageQueue, updateMessageStatus, type OutboxItem } from '../services/message';
import { sortByTimeThenId } from '../utils/sort';

const STATUS_COLOR: Record<string, string> = {
  pending: 'gold',
  sent: 'blue',
  done: 'green',
  failed: 'red',
};

const STATUS_OPTIONS = [
  { value: 'pending', label: 'pending（待投递）' },
  { value: 'sent', label: 'sent（已发 MQ）' },
  { value: 'done', label: 'done（已处理）' },
  { value: 'failed', label: 'failed（失败超限）' },
];

export default function MessageQueueList() {
  const [data, setData] = useState<OutboxItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [status, setStatus] = useState<string | undefined>();
  const [drawerOutbox, setDrawerOutbox] = useState<(OutboxItem & { payload?: any }) | null>(null);
  const { message } = AntdApp.useApp();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listMessageQueue({ page, page_size: pageSize, status });
      setData(sortByTimeThenId(res.items));
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const change = async (id: string, target: string) => {
    try {
      await updateMessageStatus(id, target);
      load();
    } catch (e) {
      // 失败直接弹错误（antd App 上下文未在简单组件内，用原生 alert 兜底）
      window.alert((e as Error).message);
    }
  };

  const openDetail = async (id: string) => {
    setDrawerOutbox(null);
    try {
      const m = await getOutbox(id);
      setDrawerOutbox(m);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const columns: ColumnsType<OutboxItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 240, render: (v: string) => <code>{v}</code> },
    { title: '类型', dataIndex: 'topic', key: 'topic', width: 160 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (v: string) => <Tag color={STATUS_COLOR[v] ?? 'default'}>{v}</Tag>,
    },
    { title: '重试', dataIndex: 'retry_count', key: 'retry_count', width: 80 },
    { title: '租户', dataIndex: 'tenant_id', key: 'tenant_id', width: 100, render: (v: number | null) => v ?? '-' },
    { title: '错误', dataIndex: 'last_error', key: 'last_error', ellipsis: true, render: (v: string | null) => v ?? '-' },
    {
      title: '发送时间',
      dataIndex: 'sent_at',
      key: 'sent_at',
      width: 170,
      render: (v?: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '创建时间',
      dataIndex: 'create_at',
      key: 'create_at',
      width: 170,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '操作',
      key: 'action',
      render: (_, record) => (
        <Space>
          <Button type="link" onClick={() => openDetail(record.id)}>
            详情
          </Button>
          <Popconfirm title="改为 pending（重投）？" onConfirm={() => change(record.id, 'pending')}>
            <Button type="link">重投</Button>
          </Popconfirm>
          <Popconfirm title="标记为 failed（不再投递）？" onConfirm={() => change(record.id, 'failed')}>
            <Button type="link" danger>
              标记失败
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        消息队列
      </Typography.Title>
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="状态"
          value={status}
          onChange={(v) => setStatus(v)}
          options={STATUS_OPTIONS}
          allowClear
          style={{ width: 180 }}
        />
        <Button type="primary" onClick={() => setPage(1)}>
          查询
        </Button>
        <Button onClick={() => load()}>刷新</Button>
        <Typography.Text type="secondary">共 {total} 条</Typography.Text>
      </Space>
      {error && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={`加载失败：${error}`}
          action={
            <Button size="small" onClick={() => load()}>
              重试
            </Button>
          }
        />
      )}
      <ProTable<OutboxItem>
        search={false}
        options={{ fullScreen: true, setting: true, density: true, reload: false }}
        rowKey="id"
        loading={loading}
        columns={columns as ProColumns<OutboxItem>[]}
        dataSource={data}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
        scroll={{ x: 'max-content' }}
      />
      <Drawer
        title={`消息详情 #${drawerOutbox?.id ?? ''}`}
        open={drawerOutbox !== null}
        onClose={() => setDrawerOutbox(null)}
        width={560}
      >
        {drawerOutbox && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="ID"><code>{drawerOutbox.id}</code></Descriptions.Item>
            <Descriptions.Item label="类型">{drawerOutbox.topic}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={STATUS_COLOR[drawerOutbox.status] ?? 'default'}>{drawerOutbox.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="重试">{drawerOutbox.retry_count}</Descriptions.Item>
            <Descriptions.Item label="租户">{drawerOutbox.tenant_id ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="错误">{drawerOutbox.last_error ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="发送时间">
              {drawerOutbox.sent_at ? dayjs(drawerOutbox.sent_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">
              {dayjs(drawerOutbox.create_at).format('YYYY-MM-DD HH:mm:ss')}
            </Descriptions.Item>
            <Descriptions.Item label="Payload">
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {JSON.stringify((drawerOutbox as any).payload ?? {}, null, 2)}
              </pre>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
}
