import { useCallback, useEffect, useState } from 'react';
import { Alert, App as AntdApp, Button, Descriptions, Drawer, Result, Space, Tooltip, Typography } from 'antd';
import { ProTable, type ProColumns } from '../components/ProTable';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import { getDeadLetter, listDeadLetters, type DeadLetterItem } from '../services/message';
import { sortByTimeThenId } from '../utils/sort';
import { hasScope } from '../services/auth';

export default function DeadLetterList() {
  const [data, setData] = useState<DeadLetterItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [drawerDL, setDrawerDL] = useState<DeadLetterItem | null>(null);
  const { message } = AntdApp.useApp();

  // 死信队列权限点（与后端 Scope 对齐）：列表按 page 拦，详情按 view 拦
  const canPage = hasScope('message:page');
  const canView = hasScope('message:view');

  const load = useCallback(async () => {
    if (!hasScope('message:page')) return;
    setLoading(true);
    setError(null);
    try {
      const res = await listDeadLetters({ page, page_size: pageSize });
      setData(sortByTimeThenId(res.items));
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize]);

  const openDetail = async (id: string) => {
    setDrawerDL(null);
    try {
      const m = await getDeadLetter(id);
      setDrawerDL(m);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ColumnsType<DeadLetterItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 240, render: (v: string) => <code>{v}</code> },
    { title: '类型', dataIndex: 'topic', key: 'topic', width: 160 },
    { title: '来源队列', dataIndex: 'origin_queue', key: 'origin_queue', width: 160, render: (v: string | null) => v ?? '-' },
    { title: '错误', dataIndex: 'error', key: 'error', ellipsis: true, render: (v: string | null) => v ?? '-' },
    { title: '重试', dataIndex: 'retry_count', key: 'retry_count', width: 80 },
    { title: '租户', dataIndex: 'tenant_id', key: 'tenant_id', width: 100, render: (v: number | null) => v ?? '-' },
    {
      title: 'Payload',
      dataIndex: 'payload',
      key: 'payload',
      ellipsis: true,
      render: (v: any) =>
        v ? (
          <Tooltip title={JSON.stringify(v)} placement="topLeft">
            <span>{JSON.stringify(v)}</span>
          </Tooltip>
        ) : (
          '-'
        ),
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
      width: 90,
      render: (_, record) => (
        canView && (
          <Button type="link" size="small" onClick={() => openDetail(record.id)}>
            详情
          </Button>
        )
      ),
    },
  ];

  if (!canPage) {
    return <Result status="403" title="无权限" subTitle="你没有查看死信队列的权限" />;
  }

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        死信队列
      </Typography.Title>
      <Space style={{ marginBottom: 16 }} wrap>
        <Button type="primary" onClick={() => load()}>
          刷新
        </Button>
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
      <ProTable<DeadLetterItem>
        search={false}
        options={{ fullScreen: true, setting: true, density: true, reload: false }}
        rowKey="id"
        loading={loading}
        columns={columns as ProColumns<DeadLetterItem>[]}
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
        title={`死信详情 #${drawerDL?.id ?? ''}`}
        open={drawerDL !== null}
        onClose={() => setDrawerDL(null)}
        width={560}
      >
        {drawerDL && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="ID"><code>{drawerDL.id}</code></Descriptions.Item>
            <Descriptions.Item label="类型">{drawerDL.topic}</Descriptions.Item>
            <Descriptions.Item label="来源队列">{drawerDL.origin_queue ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="重试">{drawerDL.retry_count}</Descriptions.Item>
            <Descriptions.Item label="租户">{drawerDL.tenant_id ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="错误">{drawerDL.error ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="创建时间">
              {dayjs(drawerDL.create_at).format('YYYY-MM-DD HH:mm:ss')}
            </Descriptions.Item>
            <Descriptions.Item label="Payload">
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {JSON.stringify(drawerDL.payload ?? {}, null, 2)}
              </pre>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
}
