import { useCallback, useEffect, useState } from 'react';
import { Alert, App as AntdApp, Button, Descriptions, Drawer, Popconfirm, Result, Select, Space, Tag, Typography } from 'antd';
import { ProTable, type ProColumns } from '@ant-design/pro-components';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import { getOutbox, listMessageQueue, updateMessageStatus, type OutboxItem } from '../services/message';
import { sortByTimeThenId } from '../utils/sort';
import { hasScope } from '../services/auth';

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

const KIND_COLOR: Record<string, string> = {
  task: 'blue',
  broadcast: 'purple',
};

const KIND_OPTIONS = [
  { value: 'task', label: 'task（工作队列）' },
  { value: 'broadcast', label: 'broadcast（广播）' },
];

/** 可通过页面勾选固定到左侧的字段（操作列不参与） */
const PIN_OPTIONS = [
  { value: 'id', label: 'ID' },
  { value: 'topic', label: '类型' },
  { value: 'message_kind', label: '消息模式' },
  { value: 'status', label: '状态' },
  { value: 'retry_count', label: '重试' },
  { value: 'tenant_id', label: '租户' },
  { value: 'last_error', label: '错误' },
  { value: 'sent_at', label: '发送时间' },
  { value: 'create_at', label: '创建时间' },
];
const PIN_STORAGE_KEY = 'message_queue_pinned_columns';
const DEFAULT_PINS = ['id', 'topic'];

export default function MessageQueueList() {
  const [data, setData] = useState<OutboxItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [status, setStatus] = useState<string | undefined>();
  const [messageKind, setMessageKind] = useState<string | undefined>();
  const [pinnedKeys, setPinnedKeys] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem(PIN_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) {
          const valid = parsed.filter((k) =>
            PIN_OPTIONS.some((opt) => opt.value === k),
          );
          if (valid.length > 0) return valid;
        }
      }
    } catch {
      // 忽略损坏的本地配置，回退默认值
    }
    return DEFAULT_PINS;
  });
  const [drawerOutbox, setDrawerOutbox] = useState<(OutboxItem & { payload?: any }) | null>(null);
  const { message } = AntdApp.useApp();

  // 消息队列权限点（与后端 Scope 对齐）：列表按 page 拦，详情按 view 拦，状态变更按 status 拦
  const canPage = hasScope('message:page');
  const canView = hasScope('message:view');
  const canStatus = hasScope('message:status');

  const load = useCallback(async () => {
    if (!hasScope('message:page')) return;
    setLoading(true);
    setError(null);
    try {
      const res = await listMessageQueue({ page, page_size: pageSize, status, message_kind: messageKind });
      setData(sortByTimeThenId(res.items));
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, status, messageKind]);

  useEffect(() => {
    void load();
  }, [load]);

  const change = async (id: string, target: string) => {
    try {
      // 标记失败时写入原因：后端会保留已有 last_error，没有则用「手动标记失败」
      await updateMessageStatus(
        id,
        target,
        target === 'failed' ? '手动标记失败' : undefined,
      );
      load();
    } catch (e) {
      // 失败直接弹错误（antd App 上下文未在简单组件内，用原生 alert 兜底）
      window.alert((e as Error).message);
    }
  };

  const query = () => {
    // 页号已是 1 时 setPage(1) 不会触发请求，必须显式 load
    if (page === 1) {
      void load();
    } else {
      setPage(1);
    }
  };

  const changePinned = (keys: string[]) => {
    setPinnedKeys(keys);
    try {
      localStorage.setItem(PIN_STORAGE_KEY, JSON.stringify(keys));
    } catch {
      // 本地存储失败不影响当前页面使用
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

  const baseColumns: ColumnsType<OutboxItem> = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 240,
      render: (v: string) => <code>{v}</code>,
    },
    {
      title: '类型',
      dataIndex: 'topic',
      key: 'topic',
      width: 160,
    },
    {
      title: '消息模式',
      dataIndex: 'message_kind',
      key: 'message_kind',
      width: 130,
      render: (v: string) => <Tag color={KIND_COLOR[v] ?? 'default'}>{v ?? '-'}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (v: string) => <Tag color={STATUS_COLOR[v] ?? 'default'}>{v}</Tag>,
    },
    { title: '重试', dataIndex: 'retry_count', key: 'retry_count', width: 80 },
    { title: '租户', dataIndex: 'tenant_id', key: 'tenant_id', width: 100, render: (v: number | null) => v ?? '-' },
    {
      title: '错误',
      dataIndex: 'last_error',
      key: 'last_error',
      width: 280,
      ellipsis: true,
      render: (v: string | null) => (v && v.trim() ? v : '-'),
    },
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
      width: 220,
      render: (_, record) => (
        <Space>
          {canView && (
            <Button type="link" onClick={() => openDetail(record.id)}>
              详情
            </Button>
          )}
          {canStatus && (
            <Popconfirm title="改为 pending（重投）？" onConfirm={() => change(record.id, 'pending')}>
              <Button type="link">重投</Button>
            </Popconfirm>
          )}
          {canStatus && (
            <Popconfirm title="标记为 failed（不再投递）？" onConfirm={() => change(record.id, 'failed')}>
              <Button type="link" danger>
                标记失败
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  // 固定列必须连续位于最左侧：按表格原顺序把选中列提到前面并加 fixed
  const pinnedSet = new Set(pinnedKeys);
  const columns: ColumnsType<OutboxItem> = [
    ...baseColumns.filter((col) => pinnedSet.has(String(col.key))),
    ...baseColumns.filter((col) => !pinnedSet.has(String(col.key))),
  ].map((col) => {
    if (!pinnedSet.has(String(col.key))) return col;
    return {
      ...col,
      fixed: 'left' as const,
      onHeaderCell: () => ({ style: { background: '#fafafa' } }),
      onCell: () => ({ style: { background: '#fff' } }),
    };
  });

  if (!canPage) {
    return <Result status="403" title="无权限" subTitle="你没有查看消息队列的权限" />;
  }

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        消息队列
      </Typography.Title>
      <Space style={{ marginBottom: 16 }} wrap>
        <Space size={4}>
          <Typography.Text type="secondary">固定列</Typography.Text>
          <Select
            mode="multiple"
            placeholder="选择要固定在左侧的字段"
            value={pinnedKeys}
            onChange={changePinned}
            options={PIN_OPTIONS}
            allowClear
            maxTagCount="responsive"
            style={{ minWidth: 240, maxWidth: 420 }}
          />
        </Space>
        <Select
          placeholder="状态"
          value={status}
          onChange={(v) => setStatus(v)}
          options={STATUS_OPTIONS}
          allowClear
          style={{ width: 180 }}
        />
        <Select
          placeholder="消息模式"
          value={messageKind}
          onChange={(v) => setMessageKind(v)}
          options={KIND_OPTIONS}
          allowClear
          style={{ width: 180 }}
        />
        <Button type="primary" onClick={query}>
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
        // 固定列必须连续；禁用列设置里的拖拽排序，避免把非固定列拖到固定列中间导致重叠
        options={{ fullScreen: true, setting: false, density: true, reload: false }}
        rowKey="id"
        loading={loading}
        columns={columns as ProColumns<OutboxItem>[]}
        dataSource={data}
        tableLayout="fixed"
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
        scroll={{ x: 1680 }}
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
            <Descriptions.Item label="消息模式">
              <Tag color={KIND_COLOR[drawerOutbox.message_kind] ?? 'default'}>{drawerOutbox.message_kind ?? '-'}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={STATUS_COLOR[drawerOutbox.status] ?? 'default'}>{drawerOutbox.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="重试">{drawerOutbox.retry_count}</Descriptions.Item>
            <Descriptions.Item label="租户">{drawerOutbox.tenant_id ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="错误">
              {drawerOutbox.last_error && drawerOutbox.last_error.trim()
                ? drawerOutbox.last_error
                : '-'}
            </Descriptions.Item>
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
