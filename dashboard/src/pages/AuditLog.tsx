import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Select, Space, Table, Tag, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import { listAuditLogs, type AuditItem } from '../services/audit';
import { listTenants, type TenantItem } from '../services/rbac';

/** 结果着色：审计里的 result 是字符串（成功/失败），未知值统一灰色 */
const RESULT_COLOR: Record<string, string> = { 成功: 'green', 失败: 'red' };

export default function AuditLog() {
  const [items, setItems] = useState<AuditItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tenantId, setTenantId] = useState<number | undefined>();
  const [limit, setLimit] = useState(200);
  const [tenantOptions, setTenantOptions] = useState<{ value: number; label: string }[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listAuditLogs({ tenant_id: tenantId, limit });
      setItems(res?.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [tenantId, limit]);

  useEffect(() => {
    void load();
  }, [load]);

  // 租户下拉只用于把 tenant_id 翻译成名字；拿不到不影响主表
  useEffect(() => {
    listTenants({ page_size: 200 })
      .then((r) =>
        setTenantOptions(r.items.map((t: TenantItem) => ({ value: t.id, label: t.name }))),
      )
      .catch(() => setTenantOptions([]));
  }, []);

  const tenantLabel = (id: number): string =>
    tenantOptions.find((o) => o.value === id)?.label ?? `#${id}`;

  const columns: ColumnsType<AuditItem> = [
    {
      title: '时间',
      dataIndex: 'create_at',
      key: 'create_at',
      width: 170,
      render: (v?: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '租户',
      dataIndex: 'tenant_id',
      key: 'tenant_id',
      width: 140,
      render: (v: number) => tenantLabel(v),
    },
    { title: '操作人', dataIndex: 'user_id', key: 'user_id', width: 90 },
    {
      title: '动作',
      dataIndex: 'action',
      key: 'action',
      width: 180,
      render: (v: string) => <code>{v}</code>,
    },
    {
      title: '对象',
      dataIndex: 'target',
      key: 'target',
      width: 140,
      render: (v: string | null) => v ?? '-',
    },
    {
      title: '详情',
      dataIndex: 'detail',
      key: 'detail',
      ellipsis: true,
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v} placement="topLeft">
            <span>{v}</span>
          </Tooltip>
        ) : (
          '-'
        ),
    },
    {
      title: '结果',
      dataIndex: 'result',
      key: 'result',
      width: 90,
      render: (v: string | null) =>
        v ? <Tag color={RESULT_COLOR[v] ?? 'default'}>{v}</Tag> : '-',
    },
    {
      title: 'traceId',
      dataIndex: 'trace_id',
      key: 'trace_id',
      width: 140,
      ellipsis: true,
      render: (v: string | null) => (v ? <code>{v}</code> : '-'),
    },
    { title: 'IP', dataIndex: 'ip', key: 'ip', width: 130, render: (v: string | null) => v ?? '-' },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        审计日志
      </Typography.Title>
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="按租户过滤"
          value={tenantId}
          onChange={(v) => setTenantId(v)}
          options={tenantOptions}
          allowClear
          style={{ width: 200 }}
        />
        <Select
          value={limit}
          onChange={setLimit}
          style={{ width: 150 }}
          options={[
            { value: 100, label: '最近 100 条' },
            { value: 200, label: '最近 200 条' },
            { value: 500, label: '最近 500 条' },
            { value: 1000, label: '最近 1000 条' },
          ]}
        />
        <Button type="primary" onClick={() => load()}>
          刷新
        </Button>
        <Typography.Text type="secondary">共 {items.length} 条（按时间倒序）</Typography.Text>
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
      <Table<AuditItem>
        rowKey="id"
        columns={columns}
        dataSource={items}
        loading={loading}
        pagination={{ pageSize: 20, showSizeChanger: false, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 'max-content' }}
      />
    </div>
  );
}
