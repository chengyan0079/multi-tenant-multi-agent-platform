import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Result,
} from 'antd';
import { ProTable, type ProColumns, type ActionType } from '../../components/ProTable';
import dayjs from 'dayjs';
import { hasScope, isTenantContext } from '../../services/auth';
import {
  listTenants,
  listUsers,
  changeUserRole,
  getUser,
  createTenantUser,
  deleteTenantUser,
  listAssignableRoles,
  type TenantItem,
  type UserItem,
} from '../../services/rbac';
import { sortByTimeThenId } from '../../utils/sort';

export default function UserList() {
  const { message } = AntdApp.useApp();
  const actionRef = useRef<ActionType>();
  const [tenantOptions, setTenantOptions] = useState<{ value: number; label: string }[]>([]);
  const [roleOptions, setRoleOptions] = useState<{ value: string; label: string }[]>([]);
  const [drawerUser, setDrawerUser] = useState<(UserItem & { enabled?: boolean }) | null>(null);
  const [editUser, setEditUser] = useState<(UserItem & { enabled?: boolean }) | null>(null);
  const [roleForm] = Form.useForm();

  useEffect(() => {
    listAssignableRoles()
      .then((names) => setRoleOptions(names.map((name) => ({ value: name, label: name }))))
      .catch(() => {});
  }, []);

  const canAdd = hasScope('user:add');
  const canDelete = hasScope('user:delete');
  const canUpdateRole = hasScope('user:update');
  const canView = hasScope('user:view');
  const canPage = hasScope('user:page');

  const [createUserOpen, setCreateUserOpen] = useState(false);
  const [creatingUser, setCreatingUser] = useState(false);
  const [createUserForm] = Form.useForm();

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
      render: (_, record) => {
        if (record.is_super_admin) return '超管';
        if (record.tenant_id == null) return '-';
        return tenantValueEnum[record.tenant_id] ?? record.tenant_id;
      },
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
      render: (_, record) => {
        const isSuper = Boolean(record.is_super_admin);
        return (
          <Space>
            {canView && (
              <Button type="link" onClick={() => openDetail(record)}>
                详情
              </Button>
            )}
            {canUpdateRole && !isSuper && (
              <Button type="link" onClick={() => openEdit(record)}>
                编辑
              </Button>
            )}
            {canDelete && isTenantContext() && !isSuper && (
              <Popconfirm
                title="确认解绑该用户？"
                onConfirm={() => onDeleteUser(record.id)}
                okText="确认"
                cancelText="取消"
              >
                <Button type="link" danger>
                  删除
                </Button>
              </Popconfirm>
            )}
          </Space>
        );
      },
    },
  ];

  const onRoleSubmit = async (values: { role: string; tenant_id: number }) => {
    if (!editUser) return;
    try {
      await changeUserRole(editUser.id, values.tenant_id, values.role);
      message.success('角色已更新');
      setEditUser(null);
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const onCreateUser = async (values: { username: string; name?: string; password: string; role: string }) => {
    setCreatingUser(true);
    try {
      await createTenantUser(values);
      message.success('用户已创建');
      setCreateUserOpen(false);
      createUserForm.resetFields();
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setCreatingUser(false);
    }
  };

  const onDeleteUser = async (userId: number) => {
    try {
      await deleteTenantUser(userId);
      message.success('用户已解绑');
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

  /** 编辑：改角色（详情只读，编辑走独立弹窗） */
  const openEdit = async (record: UserItem) => {
    try {
      setEditUser(await getUser(record.id));
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  if (!canPage) {
    return <Result status="403" title="无权限" subTitle="你没有查看用户管理的权限" />;
  }

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
        toolBarRender={() => [
          canAdd && isTenantContext() ? (
            <Button key="add" type="primary" onClick={() => setCreateUserOpen(true)}>
              新建用户
            </Button>
          ) : null,
        ]}
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
          </>
        )}
      </Drawer>
      <Modal
        title={`编辑用户 #${editUser?.id ?? ''}`}
        open={editUser !== null}
        onCancel={() => setEditUser(null)}
        onOk={() => roleForm.submit()}
        destroyOnClose
      >
        <Form
          form={roleForm}
          layout="vertical"
          onFinish={onRoleSubmit}
          initialValues={{ role: 'student', tenant_id: editUser?.tenant_id }}
        >
          <Form.Item name="tenant_id" label="目标租户" rules={[{ required: true }]}>
            <Select options={tenantOptions} />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select options={roleOptions} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="新建用户"
        open={createUserOpen}
        onCancel={() => setCreateUserOpen(false)}
        onOk={() => createUserForm.submit()}
        confirmLoading={creatingUser}
        destroyOnClose
      >
        <Form
          form={createUserForm}
          layout="vertical"
          onFinish={onCreateUser}
          initialValues={{ role: 'student' }}
        >
          <Form.Item name="username" label="登录名" rules={[{ required: true, message: '请输入登录名' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="name" label="显示名">
            <Input />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select options={roleOptions} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
