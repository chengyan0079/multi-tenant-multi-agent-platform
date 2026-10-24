import { useEffect, useState } from 'react';
import { Alert, Card, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';

import {
  listRequests,
  OP_TYPE,
  REQUEST_STATUS,
  type ConfigRequestItem,
} from '../services/configCenter';

export default function ConfigCenter() {
  const [items, setItems] = useState<ConfigRequestItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await listRequests({ page: 1, page_size: 20 });
        setItems(res?.items ?? []);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, []);

  const columns: ColumnsType<ConfigRequestItem> = [
    { title: 'namespace', dataIndex: 'namespace', key: 'namespace' },
    { title: 'group', dataIndex: 'group_id', key: 'group_id' },
    { title: 'dataId', dataIndex: 'data_id', key: 'data_id' },
    {
      title: '操作',
      dataIndex: 'op_type',
      key: 'op_type',
      render: (v: number) => <Tag>{OP_TYPE[v] ?? v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (v: number) => {
        const label = REQUEST_STATUS[v] ?? String(v);
        return <Tag color={v === 3 ? 'green' : v === 2 ? 'red' : 'orange'}>{label}</Tag>;
      },
    },
    { title: '申请人', dataIndex: 'applicant_user_id', key: 'applicant_user_id' },
    { title: '复核人', dataIndex: 'reviewer_user_id', key: 'reviewer_user_id' },
    { title: '申请时间', dataIndex: 'create_at', key: 'create_at' },
  ];

  return (
    <Card title={<Typography.Title level={4} style={{ margin: 0 }}>配置中心</Typography.Title>}>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        {error && <Alert type="error" showIcon message={`加载失败：${error}`} />}
        <Table<ConfigRequestItem>
          rowKey="id"
          columns={columns}
          dataSource={items}
          loading={loading}
          pagination={false}
          scroll={{ x: 'max-content' }}
        />
      </Space>
    </Card>
  );
}
