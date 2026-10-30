import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Descriptions, Drawer, Select, Space, Tag, Typography } from 'antd';
import { ProTable, type ProColumns } from '@ant-design/pro-components';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import { listLoginLogs, type LoginLogItem } from '../services/audit';
import { listTenants, type TenantItem } from '../services/rbac';
import { sortByTimeThenId } from '../utils/sort';

export default function AuditLoginLog() {
  const [items, setItems] = useState<LoginLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tenantId, setTenantId] = useState<number | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [drawerLog, setDrawerLog] = useState<LoginLogItem | null>(null);
  const [tenantOptions, setTenantOptions] = useState<{ value: number; label: string }[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listLoginLogs({ tenant_id: tenantId, page, page_size: pageSize });
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

  const columns: ColumnsType<LoginLogItem> = [
    {
      title: '时间',
      dataIndex: 'create_at',
      key: 'create_at',
      width: 170,
      render: (v?: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    { title: '租户', dataIndex: 'tenant_id', key: 'tenant_id', width: 140, render: (v: number | null) => tenantLabel(v) },
    { title: '用户名', dataIndex: 'username', key: 'username', width: 120, render: (v: string | null) => v ?? '-' },
    { title: '登录方式', dataIndex: 'login_type', key: 'login_type', width: 100 },
    {
      title: '结果',
      dataIndex: 'success',
      key: 'success',
      width: 90,
      render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '成功' : '失败'}</Tag>,
    },
    { title: '失败原因', dataIndex: 'fail_reason', key: 'fail_reason', ellipsis: true, render: (v: string | null) => v ?? '-' },
    { title: 'IP', dataIndex: 'ip', key: 'ip', width: 130, render: (v: string | null) => v ?? '-' },
    { title: '客户端', dataIndex: 'client', key: 'client', width: 120, render: (v: string | null) => v ?? '-' },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_, row: LoginLogItem) => (
        <Button type="link" size="small" onClick={() => setDrawerLog(row)}>
          详情
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        登录日志
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
      <ProTable<LoginLogItem>
        search={false}
        options={{ fullScreen: true, setting: true, density: true, reload: false }}
        rowKey="id"
        columns={columns as ProColumns<LoginLogItem>[]}
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
        title={`登录详情 #${drawerLog?.id ?? ''}`}
        open={drawerLog !== null}
        onClose={() => setDrawerLog(null)}
        width={520}
      >
        {drawerLog && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="ID">{drawerLog.id}</Descriptions.Item>
            <Descriptions.Item label="租户">{tenantLabel(drawerLog.tenant_id)}</Descriptions.Item>
            <Descriptions.Item label="用户名">{drawerLog.username ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="登录方式">{drawerLog.login_type}</Descriptions.Item>
            <Descriptions.Item label="结果">{drawerLog.success ? '成功' : '失败'}</Descriptions.Item>
            <Descriptions.Item label="失败原因">{drawerLog.fail_reason ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="IP">{drawerLog.ip ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="客户端">{drawerLog.client ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="User-Agent">{drawerLog.user_agent ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="traceId">{drawerLog.trace_id ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="时间">
              {drawerLog.create_at ? dayjs(drawerLog.create_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
}
