import { Card, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';

import { auditLogs, type AuditItem } from '../mock/tables';

const columns: ColumnsType<AuditItem> = [
  { title: '时间', dataIndex: 'time', key: 'time' },
  { title: '操作人', dataIndex: 'user', key: 'user' },
  { title: '动作', dataIndex: 'action', key: 'action' },
  { title: '资源', dataIndex: 'resource', key: 'resource' },
  {
    title: '结果',
    dataIndex: 'result',
    key: 'result',
    render: (value: string) => {
      const color = value === '成功' ? 'green' : value === '失败' ? 'red' : 'orange';
      return <Tag color={color}>{value}</Tag>;
    },
  },
  { title: 'traceId', dataIndex: 'traceId', key: 'traceId' },
];

export default function AuditLog() {
  return (
    <Card title={<Typography.Title level={4} style={{ margin: 0 }}>审计日志</Typography.Title>}>
      <Table<AuditItem>
        columns={columns}
        dataSource={auditLogs}
        pagination={false}
        scroll={{ x: 'max-content' }}
      />
    </Card>
  );
}
