import { useCallback, useRef, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Switch,
  Typography,
} from 'antd';
import { ProTable, type ProColumns, type ActionType } from '@ant-design/pro-components';
import dayjs from 'dayjs';
import {
  createTenant,
  listTenants,
  deleteTenant,
  setTenantStatus,
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

  const [detailTenant, setDetailTenant] = useState<(TenantItem & { updated_at?: string }) | null>(null);

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
      render: (_: any, record: TenantItem) => (
        <Popconfirm
          title={record.enabled ? '确认停用该租户？' : '确认启用该租户？'}
          description="停用将使其下所有用户无法登录"
          onConfirm={() => onToggleStatus(record)}
          okText="确认"
          cancelText="取消"
        >
          <Switch checked={record.enabled} onChange={() => {}} />
        </Popconfirm>
      ),
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
        <Space>
          <Button type="link" onClick={() => openDetail(record.id)}>
            详情
          </Button>
          <Popconfirm
            title="确认删除该租户？"
            description="删除后不可恢复"
            onConfirm={() => onDelete(record.id)}
            okText="确认"
            cancelText="取消"
          >
            <Button type="link" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const onCreate = async (values: {
    name: string;
    manager_username: string;
    manager_name?: string;
    manager_password: string;
  }) => {
    setCreating(true);
    try {
      await createTenant({
        name: values.name,
        manager: {
          username: values.manager_username,
          name: values.manager_name,
          password: values.manager_password,
        },
      });
      message.success('租户已创建，主租户用户已绑定');
      setCreateOpen(false);
      createForm.resetFields();
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const openDetail = async (id: number) => {
    try {
      const t = await getTenant(id);
      setDetailTenant(t);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const onToggleStatus = async (record: TenantItem) => {
    try {
      await setTenantStatus(record.id, !record.enabled);
      message.success(record.enabled ? '已停用' : '已启用');
      actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const onDelete = async (id: number) => {
    try {
      await deleteTenant(id);
      message.success('租户已删除');
      actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
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
      {/* 详情抽屉：只读展示，不与编辑共用 */}
      <Drawer
        title={`租户详情 #${detailTenant?.id ?? ''}`}
        open={detailTenant !== null}
        onClose={() => setDetailTenant(null)}
        width={460}
      >
        {detailTenant && (
          <>
            <p><b>名称：</b>{detailTenant.name}</p>
            <p><b>状态：</b>{detailTenant.enabled ? '启用' : '停用'}</p>
            <p><b>管理员：</b>{detailTenant.manager_username ?? '-'}</p>
            <p><b>用户数：</b>{detailTenant.user_count ?? 0}</p>
            <p>
              <b>创建时间：</b>
              {detailTenant.create_at ? dayjs(detailTenant.create_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
            </p>
            <p>
              <b>更新时间：</b>
              {detailTenant.updated_at ? dayjs(detailTenant.updated_at).format('YYYY-MM-DD HH:mm') : '-'}
            </p>
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
          <Typography.Title level={5}>主租户用户（自动创建并授权 tenant_admin）</Typography.Title>
          <Form.Item
            name="manager_username"
            label="登录名"
            rules={[{ required: true, message: '请输入主用户登录名' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="manager_name" label="显示名">
            <Input />
          </Form.Item>
          <Form.Item
            name="manager_password"
            label="密码"
            rules={[{ required: true, message: '请输入主用户密码' }]}
          >
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
