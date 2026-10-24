import { Card, Col, Row, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';

import { rbacBindings, roles, type RbacItem, type RoleItem } from '../mock/tables';

const bindingColumns: ColumnsType<RbacItem> = [
  { title: '用户ID', dataIndex: 'userId', key: 'userId' },
  { title: '用户名', dataIndex: 'userName', key: 'userName' },
  { title: '租户ID', dataIndex: 'tenantId', key: 'tenantId' },
  { title: '租户名', dataIndex: 'tenantName', key: 'tenantName' },
  {
    title: '角色',
    dataIndex: 'role',
    key: 'role',
    render: (value: string) => <Tag color="blue">{value}</Tag>,
  },
];

const roleColumns: ColumnsType<RoleItem> = [
  { title: 'role_id', dataIndex: 'roleId', key: 'roleId' },
  { title: '角色名', dataIndex: 'name', key: 'name' },
  { title: '说明', dataIndex: 'description', key: 'description' },
  { title: '权限点（scope）', dataIndex: 'scopes', key: 'scopes' },
];

export default function Rbac() {
  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        权限中心（RBAC）
      </Typography.Title>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card title="用户-租户-角色分配">
            <Table<RbacItem>
              size="small"
              columns={bindingColumns}
              dataSource={rbacBindings}
              pagination={false}
              scroll={{ x: 640 }}
            />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="内置角色">
            <Table<RoleItem>
              size="small"
              columns={roleColumns}
              dataSource={roles}
              pagination={false}
              scroll={{ x: 520 }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
