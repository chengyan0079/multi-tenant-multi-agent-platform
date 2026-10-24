import { Card, Switch, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';

import { tools, type ToolItem } from '../mock/tables';

const columns: ColumnsType<ToolItem> = [
  { title: '工具名', dataIndex: 'name', key: 'name' },
  { title: '所属插件', dataIndex: 'plugin', key: 'plugin' },
  { title: '类型', dataIndex: 'type', key: 'type', render: (v: string) => <Tag>{v}</Tag> },
  {
    title: '启用',
    dataIndex: 'enabled',
    key: 'enabled',
    render: (value: boolean) => <Switch checked={value} disabled />,
  },
  { title: '调用次数', dataIndex: 'calls', key: 'calls' },
];

export default function Tools() {
  return (
    <Card title={<Typography.Title level={4} style={{ margin: 0 }}>工具与插件</Typography.Title>}>
      <Table<ToolItem>
        columns={columns}
        dataSource={tools}
        pagination={false}
        scroll={{ x: 'max-content' }}
      />
    </Card>
  );
}
