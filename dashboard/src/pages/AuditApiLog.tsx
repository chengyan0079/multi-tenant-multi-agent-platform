import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Descriptions, Drawer, Select, Space, Tag, Typography } from 'antd';
import { ProTable, type ProColumns } from '@ant-design/pro-components';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import { listApiLogs, type ApiLogItem } from '../services/audit';
import { listTenants, type TenantItem } from '../services/rbac';
import { sortByTimeThenId } from '../utils/sort';

const statusColor = (code: number | null): string => {
  if (code == null) return 'default';
  if (code < 300) return 'green';
  if (code < 400) return 'blue';
  if (code < 500) return 'orange';
  return 'red';
};

/** 旧数据 route 可能不含 /api/v1 前缀，按 path 段对齐补全，保证展示的是后端完整路由。 */
const fullRoute = (path: string, route: string | null): string | null => {
  if (!route) return route;
  const p = path.split('/').filter(Boolean);
  const t = route.split('/').filter(Boolean);
  if (!t.length || t.length > p.length) return route;
  return `/${[...p.slice(0, p.length - t.length), ...t].join('/')}`;
};

export default function AuditApiLog() {
  const [items, setItems] = useState<ApiLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tenantId, setTenantId] = useState<number | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [drawerLog, setDrawerLog] = useState<ApiLogItem | null>(null);
  const [tenantOptions, setTenantOptions] = useState<{ value: number; label: string }[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listApiLogs({ tenant_id: tenantId, page, page_size: pageSize });
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

  useEffect(() => {
    listTenants({ page_size: 200 })
      .then((r) => setTenantOptions(r.items.map((t: TenantItem) => ({ value: t.id, label: t.name }))))
      .catch(() => setTenantOptions([]));
  }, []);

  const tenantLabel = (id: number | null): string =>
    id == null ? '-' : (tenantOptions.find((o) => o.value === id)?.label ?? `#${id}`);

  const columns: ColumnsType<ApiLogItem> = [
    {
      title: '时间',
      dataIndex: 'req_time',
      key: 'req_time',
      width: 170,
      render: (v?: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    { title: '租户', dataIndex: 'tenant_id', key: 'tenant_id', width: 130, render: (v: number | null) => tenantLabel(v) },
    { title: '方法', dataIndex: 'method', key: 'method', width: 80, render: (v: string) => <Tag>{v}</Tag> },
    { title: '后端 API 路径', dataIndex: 'path', key: 'path', ellipsis: true, render: (v: string) => <code>{v}</code> },
    {
      title: '路由模板',
      dataIndex: 'route',
      key: 'route',
      width: 240,
      ellipsis: true,
      render: (_: string | null, row: ApiLogItem) => {
        const r = fullRoute(row.path, row.route);
        return r ? <code>{r}</code> : '-';
      },
    },
    {
      title: '状态码',
      dataIndex: 'status_code',
      key: 'status_code',
      width: 90,
      render: (v: number | null) => <Tag color={statusColor(v)}>{v ?? '-'}</Tag>,
    },
    {
      title: '耗时',
      dataIndex: 'cost_ms',
      key: 'cost_ms',
      width: 100,
      render: (v: number | null) => (v == null ? '-' : `${v} ms`),
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_, row: ApiLogItem) => (
        <Button type="link" size="small" onClick={() => setDrawerLog(row)}>
          详情
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        API 调用日志
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
      <ProTable<ApiLogItem>
        search={false}
        options={{ fullScreen: true, setting: true, density: true, reload: false }}
        rowKey="id"
        columns={columns as ProColumns<ApiLogItem>[]}
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
        title={`API 调用详情 #${drawerLog?.id ?? ''}`}
        open={drawerLog !== null}
        onClose={() => setDrawerLog(null)}
        width={560}
      >
        {drawerLog && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="ID">{drawerLog.id}</Descriptions.Item>
            <Descriptions.Item label="traceId">{drawerLog.trace_id ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="调用方">{drawerLog.caller ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="租户">{tenantLabel(drawerLog.tenant_id)}</Descriptions.Item>
            <Descriptions.Item label="用户">{drawerLog.user_id ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="方法">{drawerLog.method}</Descriptions.Item>
            <Descriptions.Item label="后端 API 路径"><code>{drawerLog.path}</code></Descriptions.Item>
            <Descriptions.Item label="路由模板">
              {drawerLog.route ? <code>{fullRoute(drawerLog.path, drawerLog.route)}</code> : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="查询串">{drawerLog.query_string ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="状态码">{drawerLog.status_code ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="耗时">{drawerLog.cost_ms == null ? '-' : `${drawerLog.cost_ms} ms`}</Descriptions.Item>
            <Descriptions.Item label="请求时间">
              {drawerLog.req_time ? dayjs(drawerLog.req_time).format('YYYY-MM-DD HH:mm:ss') : '-'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
}
