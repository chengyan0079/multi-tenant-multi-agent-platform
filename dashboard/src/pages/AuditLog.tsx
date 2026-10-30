import { useCallback, useEffect, useState } from 'react';
import { Alert, App as AntdApp, Button, Descriptions, Drawer, Select, Space, Tag, Tooltip, Typography } from 'antd';
import { ProTable, type ProColumns } from '@ant-design/pro-components';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import { getAuditLog, listAuditLogs, type AuditItem } from '../services/audit';
import { listTenants, type TenantItem } from '../services/rbac';
import { sortByTimeThenId } from '../utils/sort';

/** 结果着色：审计里的 result 是字符串（成功/失败），未知值统一灰色 */
const RESULT_COLOR: Record<string, string> = { 成功: 'green', 失败: 'red' };

export default function AuditLog() {
  const [items, setItems] = useState<AuditItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tenantId, setTenantId] = useState<number | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [drawerLog, setDrawerLog] = useState<AuditItem | null>(null);
  const { message } = AntdApp.useApp();
  const [tenantOptions, setTenantOptions] = useState<{ value: number; label: string }[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listAuditLogs({ tenant_id: tenantId, page, page_size: pageSize });
      setItems(sortByTimeThenId(res?.items ?? []));
      setTotal(res?.total ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [tenantId, page, pageSize]);

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

  const openDetail = async (id: string) => {
    setDrawerLog(null);
    try {
      const log = await getAuditLog(id);
      setDrawerLog(log);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

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
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_, row: AuditItem) => (
        <Button type="link" size="small" onClick={() => openDetail(row.id)}>
          详情
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        业务审计
      </Typography.Title>
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="按租户过滤"
          value={tenantId}
          onChange={(v) => {
            setTenantId(v);
            setPage(1);
          }}
          options={tenantOptions}
          allowClear
          style={{ width: 200 }}
        />
        <Button type="primary" onClick={() => load()}>
          刷新
        </Button>
        <Typography.Text type="secondary">共 {total} 条（按时间倒序）</Typography.Text>
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
      <ProTable<AuditItem>
        search={false}
        options={{ fullScreen: true, setting: true, density: true, reload: false }}
        rowKey="id"
        columns={columns as ProColumns<AuditItem>[]}
        dataSource={items}
        loading={loading}
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
        title={`审计详情 #${drawerLog?.id ?? ''}`}
        open={drawerLog !== null}
        onClose={() => setDrawerLog(null)}
        width={520}
      >
        {drawerLog && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="ID">{drawerLog.id}</Descriptions.Item>
            <Descriptions.Item label="租户">{drawerLog.tenant_id}</Descriptions.Item>
            <Descriptions.Item label="操作人">{drawerLog.user_id}</Descriptions.Item>
            <Descriptions.Item label="动作"><code>{drawerLog.action}</code></Descriptions.Item>
            <Descriptions.Item label="对象">{drawerLog.target ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="详情">{drawerLog.detail ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="结果">{drawerLog.result ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="traceId">{drawerLog.trace_id ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="IP">{drawerLog.ip ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="时间">{drawerLog.create_at ? dayjs(drawerLog.create_at).format('YYYY-MM-DD HH:mm:ss') : '-'}</Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
}
