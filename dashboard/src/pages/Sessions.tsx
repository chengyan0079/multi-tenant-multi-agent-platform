import { Card, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';

import { sessions, type SessionItem } from '../mock/tables';

const statusColor: Record<string, string> = {
  进行中: 'blue',
  已完成: 'green',
  转人工: 'orange',
  失败: 'red',
};

const columns: ColumnsType<SessionItem> = [
  { title: '会话ID', dataIndex: 'threadId', key: 'threadId' },
  { title: '用户', dataIndex: 'user', key: 'user' },
  { title: '租户', dataIndex: 'tenant', key: 'tenant' },
  { title: '智能体', dataIndex: 'agent', key: 'agent' },
  {
    title: '状态',
    dataIndex: 'status',
    key: 'status',
    render: (value: string) => <Tag color={statusColor[value] ?? 'default'}>{value}</Tag>,
  },
  { title: '消息数', dataIndex: 'messages', key: 'messages' },
  { title: '创建时间', dataIndex: 'createdAt', key: 'createdAt' },
];

export default function Sessions() {
  return (
    <Card title={<Typography.Title level={4} style={{ margin: 0 }}>会话运行</Typography.Title>}>
      <Table<SessionItem>
        columns={columns}
        dataSource={sessions}
        pagination={false}
        scroll={{ x: 'max-content' }}
      />
    </Card>
  );
}
