import { useCallback, useRef, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Switch,
  Tag,
  Typography,
} from 'antd';
import { ProTable, type ProColumns, type ActionType } from '@ant-design/pro-components';
import dayjs from 'dayjs';
import {
  createTenant,
  listTenants,
  setTenantManager,
  setTenantStatus,
  updateTenant,
  getTenant,
  type TenantItem,
} from '../../services/rbac';
import { sortByTimeThenId } from '../../utils/sort';

export default function TenantList() {
  const { message } = AntdApp.useApp();
  const actionRef = useRef<ActionType>();
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createForm] = Form.useForm();

  const [drawerTenant, setDrawerTenant] = useState<(TenantItem & { updated_at?: string }) | null>(null);
  const [updateForm] = Form.useForm();
  const [mgrForm] = Form.useForm();

  const request = useCallback(async (params: any) => {
    const range = params.create_at as [any, any] | undefined;
    const res = await listTenants({
      page: params.current ?? 1,
      page_size: params.pageSize ?? 20,
      name: params.name || undefined,
      created_from: range?.[0] ? dayjs(range[0]).format('YYYY-MM-DD') : undefined,
      created_to: range?.[1] ? dayjs(range[1]).format('YYYY-MM-DD') : undefined,
    });
    return { data: sortByTimeThenId(res.items), success: true, total: res.total };
  }, []);

  const columns: ProColumns<TenantItem>[] = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80, search: false },
    { title: '名称', dataIndex: 'name', key: 'name', valueType: 'text' },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      search: false,
      render: (value: any) => <Tag color={value ? 'green' : 'red'}>{value ? '启用' : '停用'}</Tag>,
    },
    { title: '管理员', dataIndex: 'manager_username', key: 'manager_username', search: false, render: (v) => v ?? '-' },
    { title: '用户数', dataIndex: 'user_count', key: 'user_count', width: 90, search: false },
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
        <Button
          type="link"
          onClick={() => {
            openDetail(record.id);
            updateForm.setFieldsValue({ name: record.name, enabled: record.enabled });
            mgrForm.setFieldsValue({ username: record.manager_username ?? '' });
          }}
        >
          详情
        </Button>
      ),
    },
  ];

  const onCreate = async (values: { name: string }) => {
    setCreating(true);
    try {
      await createTenant(values.name);
      message.success('租户已创建');
      setCreateOpen(false);
      createForm.resetFields();
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const onUpdate = async (values: { name?: string; enabled?: boolean }) => {
    if (!drawerTenant) return;
    try {
      // 启停走专用 status 端点；改名走 updateTenant
      if (values.enabled !== drawerTenant.enabled) {
        await setTenantStatus(drawerTenant.id, values.enabled ?? true);
      }
      if (values.name && values.name !== drawerTenant.name) {
        await updateTenant(drawerTenant.id, { name: values.name });
      }
      message.success('租户已更新');
      setDrawerTenant(null);
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const openDetail = async (id: number) => {
    try {
      const t = await getTenant(id);
      setDrawerTenant(t);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const onManager = async (values: { username: string; password?: string }) => {
    if (!drawerTenant) return;
    try {
      await setTenantManager(drawerTenant.id, values.username, values.password);
      message.success('管理员已更新');
      setDrawerTenant(null);
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  return (
    <div>
      <ProTable<TenantItem>
        headerTitle="租户管理"
        actionRef={actionRef}
        toolBarRender={() => [
          <Button key="add" type="primary" onClick={() => setCreateOpen(true)}>
            新建租户
          </Button>,
        ]}
        rowKey="id"
        columns={columns}
        request={request}
        search={{ labelWidth: 'auto' }}
        options={{ fullScreen: true, setting: true, density: true, reload: true }}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        scroll={{ x: 'max-content' }}
      />
      <Drawer
        title={`租户详情 #${drawerTenant?.id ?? ''}`}
        open={drawerTenant !== null}
        onClose={() => setDrawerTenant(null)}
        width={460}
      >
        {drawerTenant && (
          <>
            <p>
              <b>创建时间：</b>
              {drawerTenant.create_at ? dayjs(drawerTenant.create_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
            </p>
            <p>
              <b>更新时间：</b>
              {drawerTenant.updated_at ? dayjs(drawerTenant.updated_at).format('YYYY-MM-DD HH:mm') : '-'}
            </p>
            <Typography.Title level={5}>改名 / 启停</Typography.Title>
            <Form form={updateForm} layout="vertical" onFinish={onUpdate}>
              <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="enabled" label="启用" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Popconfirm
                title="确认保存改名 / 启停？"
                description="停用租户将使其下所有用户无法登录"
                onConfirm={() => updateForm.submit()}
                okText="保存"
                cancelText="取消"
              >
                <Button type="primary">保存</Button>
              </Popconfirm>
            </Form>
            <Typography.Title level={5} style={{ marginTop: 24 }}>
              更换管理员
            </Typography.Title>
            <Form form={mgrForm} layout="vertical" onFinish={onManager}>
              <Form.Item name="username" label="管理员用户名" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="password" label="密码（新用户必填）">
                <Input.Password />
              </Form.Item>
              <Popconfirm
                title="确认更换管理员？"
                description="原管理员将降级为普通用户，且无法撤销"
                onConfirm={() => mgrForm.submit()}
                okText="提交"
                cancelText="取消"
              >
                <Button type="primary">提交</Button>
              </Popconfirm>
            </Form>
          </>
        )}
      </Drawer>
      <Modal
        title="新建租户"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        confirmLoading={creating}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" onFinish={onCreate}>
          <Form.Item
            name="name"
            label="租户名称"
            rules={[{ required: true, message: '请输入租户名称' }]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
