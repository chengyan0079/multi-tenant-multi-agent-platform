import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  App as AntdApp,
  Button,
  DatePicker,
  Drawer,
  Form,
  Input,
  Select,
  Space,
  Table,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs, { Dayjs } from 'dayjs';
import { listTenants, listUsers, changeUserRole, type TenantItem, type UserItem } from '../../services/rbac';

const ROLE_OPTIONS = [
  { value: 'student', label: 'student' },
  { value: 'teacher', label: 'teacher' },
  { value: 'tenant_admin', label: 'tenant_admin' },
];

export default function UserList() {
  const { message } = AntdApp.useApp();
  const [data, setData] = useState<UserItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [username, setUsername] = useState('');
  const [tenantId, setTenantId] = useState<number | undefined>();
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [tenantOptions, setTenantOptions] = useState<{ value: number; label: string }[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [drawerUser, setDrawerUser] = useState<UserItem | null>(null);
  const [roleForm] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listUsers({
        page,
        page_size: pageSize,
        username: username || undefined,
        tenant_id: tenantId,
        created_from: range ? range[0].format('YYYY-MM-DD') : undefined,
        created_to: range ? range[1].format('YYYY-MM-DD') : undefined,
      });
      setData(res.items);
      setTotal(res.total);
    } catch (e) {
      // 加载失败要把原因展示出来，否则页面上只表现为「空表格」
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, username, tenantId, range]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    listTenants({ page_size: 200 }).then((r) =>
      setTenantOptions(r.items.map((t: TenantItem) => ({ value: t.id, label: t.name }))),
    );
  }, []);

  const columns: ColumnsType<UserItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80 },
    { title: '用户名', dataIndex: 'username', key: 'username' },
    { title: '显示名', dataIndex: 'name', key: 'name' },
    { title: '主租户ID', dataIndex: 'tenant_id', key: 'tenant_id', width: 100 },
    {
      title: '创建时间',
      dataIndex: 'create_at',
      key: 'create_at',
      render: (v?: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      render: (_, record) => (
        <Button type="link" onClick={() => setDrawerUser(record)}>
          详情
        </Button>
      ),
    },
  ];

  const onSearch = () => {
    setPage(1);
  };

  const onRoleSubmit = async (values: { role: string; tenant_id: number }) => {
    if (!drawerUser) return;
    try {
      await changeUserRole(drawerUser.id, values.tenant_id, values.role);
      message.success('角色已更新');
      setDrawerUser(null);
      load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        用户管理
      </Typography.Title>
      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          placeholder="用户名"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          allowClear
          style={{ width: 160 }}
        />
        <Select
          placeholder="按租户过滤"
          value={tenantId}
          onChange={(v) => setTenantId(v)}
          options={tenantOptions}
          allowClear
          style={{ width: 180 }}
        />
        <DatePicker.RangePicker
          value={range}
          onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)}
          style={{ width: 280 }}
        />
        <Button type="primary" onClick={onSearch}>
          查询
        </Button>
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
      <Table<UserItem>
        rowKey="id"
        loading={loading}
        columns={columns}
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
      />
      <Drawer
        title={`用户详情 #${drawerUser?.id ?? ''}`}
        open={drawerUser !== null}
        onClose={() => setDrawerUser(null)}
        width={420}
      >
        {drawerUser && (
          <>
            <p>
              <b>用户名：</b>
              {drawerUser.username}
            </p>
            <p>
              <b>显示名：</b>
              {drawerUser.name}
            </p>
            <p>
              <b>主租户ID：</b>
              {drawerUser.tenant_id}
            </p>
            <p>
              <b>创建时间：</b>
              {drawerUser.create_at ? dayjs(drawerUser.create_at).format('YYYY-MM-DD HH:mm') : '-'}
            </p>
            <Typography.Title level={5}>修改角色</Typography.Title>
            <Form
              form={roleForm}
              layout="vertical"
              initialValues={{ role: 'student', tenant_id: drawerUser.tenant_id }}
              onFinish={onRoleSubmit}
            >
              <Form.Item name="tenant_id" label="目标租户" rules={[{ required: true }]}>
                <Select options={tenantOptions} />
              </Form.Item>
              <Form.Item name="role" label="角色" rules={[{ required: true }]}>
                <Select options={ROLE_OPTIONS} />
              </Form.Item>
              <Button type="primary" htmlType="submit">
                提交
              </Button>
            </Form>
          </>
        )}
      </Drawer>
    </div>
  );
}
