import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Drawer,
  Form,
  Popconfirm,
  Select,
  Typography,
} from 'antd';
import { ProTable, type ProColumns, type ActionType } from '@ant-design/pro-components';
import dayjs from 'dayjs';
import { listTenants, listUsers, changeUserRole, getUser, type TenantItem, type UserItem } from '../../services/rbac';
import { sortByTimeThenId } from '../../utils/sort';

const ROLE_OPTIONS = [
  { value: 'student', label: 'student' },
  { value: 'teacher', label: 'teacher' },
  { value: 'tenant_admin', label: 'tenant_admin' },
];

export default function UserList() {
  const { message } = AntdApp.useApp();
  const actionRef = useRef<ActionType>();
  const [tenantOptions, setTenantOptions] = useState<{ value: number; label: string }[]>([]);
  const [drawerUser, setDrawerUser] = useState<(UserItem & { enabled?: boolean }) | null>(null);
  const [roleForm] = Form.useForm();

  const tenantValueEnum = useMemo(
    () => Object.fromEntries(tenantOptions.map((o) => [o.value, o.label])),
    [tenantOptions],
  );

  const request = useCallback(async (params: any) => {
    const range = params.create_at as [any, any] | undefined;
    const res = await listUsers({
      page: params.current ?? 1,
      page_size: params.pageSize ?? 20,
      username: params.username || undefined,
      tenant_id: params.tenant_id,
      created_from: range?.[0] ? dayjs(range[0]).format('YYYY-MM-DD') : undefined,
      created_to: range?.[1] ? dayjs(range[1]).format('YYYY-MM-DD') : undefined,
    });
    return { data: sortByTimeThenId(res.items), success: true, total: res.total };
  }, []);

  useEffect(() => {
    listTenants({ page_size: 200 }).then((r) =>
      setTenantOptions(r.items.map((t: TenantItem) => ({ value: t.id, label: t.name }))),
    );
  }, []);

  const columns: ProColumns<UserItem>[] = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80, search: false },
    { title: '用户名', dataIndex: 'username', key: 'username', valueType: 'text' },
    { title: '显示名', dataIndex: 'name', key: 'name', search: false },
    {
      title: '租户ID',
      dataIndex: 'tenant_id',
      key: 'tenant_id',
      width: 100,
      valueType: 'select',
      valueEnum: tenantValueEnum,
    },
    {
      title: '创建时间',
      dataIndex: 'create_at',
      key: 'create_at',
      search: false,
      render: (value: any) => (value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '创建时间',
      dataIndex: 'create_at',
      key: 'create_at_range',
      hideInTable: true,
      valueType: 'dateRange',
    },
    {
      title: '操作',
      key: 'action',
      search: false,
      render: (_, record) => (
        <Button type="link" onClick={() => openDetail(record)}>
          详情
        </Button>
      ),
    },
  ];

  const onRoleSubmit = async (values: { role: string; tenant_id: number }) => {
    if (!drawerUser) return;
    try {
      await changeUserRole(drawerUser.id, values.tenant_id, values.role);
      message.success('角色已更新');
      setDrawerUser(null);
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const openDetail = async (record: UserItem) => {
    try {
      const u = await getUser(record.id);
      setDrawerUser(u);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div>
      <ProTable<UserItem>
        headerTitle="用户管理"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={request}
        search={{ labelWidth: 'auto' }}
        options={{ fullScreen: true, setting: true, density: true, reload: true }}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        scroll={{ x: 'max-content' }}
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
              <b>是否启用：</b>
              {drawerUser.enabled ? '是' : '否'}
            </p>
            <p>
              <b>显示名：</b>
              {drawerUser.name}
            </p>
            <p>
              <b>租户ID：</b>
              {drawerUser.tenant_id}
            </p>
            <p>
              <b>创建时间：</b>
              {drawerUser.create_at ? dayjs(drawerUser.create_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
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
              <Popconfirm
                title="确认修改用户角色？"
                description="角色变更立即生效，影响该用户权限"
                onConfirm={() => roleForm.submit()}
                okText="提交"
                cancelText="取消"
              >
                <Button type="primary">提交</Button>
              </Popconfirm>
            </Form>
          </>
        )}
      </Drawer>
    </div>
  );
}
