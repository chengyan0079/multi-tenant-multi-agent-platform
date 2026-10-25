import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  App as AntdApp,
  Button,
  DatePicker,
  Drawer,
  Form,
  Input,
  Modal,
  Switch,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs, { Dayjs } from 'dayjs';
import {
  createTenant,
  listTenants,
  setTenantManager,
  updateTenant,
  type TenantItem,
} from '../../services/rbac';

export default function TenantList() {
  const { message } = AntdApp.useApp();
  const [data, setData] = useState<TenantItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [name, setName] = useState('');
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createForm] = Form.useForm();

  const [drawerTenant, setDrawerTenant] = useState<TenantItem | null>(null);
  const [updateForm] = Form.useForm();
  const [mgrForm] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listTenants({
        page,
        page_size: pageSize,
        name: name || undefined,
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
  }, [page, pageSize, name, range]);

  useEffect(() => {
    load();
  }, [load]);

  const columns: ColumnsType<TenantItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80 },
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '停用'}</Tag>,
    },
    {
      title: '主租户',
      dataIndex: 'is_primary',
      key: 'is_primary',
      render: (v: boolean) => (v ? <Tag color="blue">主租户</Tag> : <></>),
    },
    { title: '管理员', dataIndex: 'manager_username', key: 'manager_username', render: (v) => v ?? '-' },
    { title: '用户数', dataIndex: 'user_count', key: 'user_count', width: 90 },
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
        <Button
          type="link"
          onClick={() => {
            setDrawerTenant(record);
            updateForm.setFieldsValue({ name: record.name, enabled: record.enabled });
            mgrForm.setFieldsValue({ username: record.manager_username ?? '' });
          }}
        >
          详情
        </Button>
      ),
    },
  ];

  const onSearch = () => {
    setPage(1);
  };

  const onCreate = async (values: { name: string }) => {
    setCreating(true);
    try {
      await createTenant(values.name);
      message.success('租户已创建');
      setCreateOpen(false);
      createForm.resetFields();
      load();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const onUpdate = async (values: { name?: string; enabled?: boolean }) => {
    if (!drawerTenant) return;
    try {
      await updateTenant(drawerTenant.id, values);
      message.success('租户已更新');
      setDrawerTenant(null);
      load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const onManager = async (values: { username: string; password?: string }) => {
    if (!drawerTenant) return;
    try {
      await setTenantManager(drawerTenant.id, values.username, values.password);
      message.success('管理员已更新');
      setDrawerTenant(null);
      load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        租户管理
        <Button type="primary" style={{ marginLeft: 16 }} onClick={() => setCreateOpen(true)}>
          新建租户
        </Button>
      </Typography.Title>
      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          placeholder="租户名"
          value={name}
          onChange={(e) => setName(e.target.value)}
          allowClear
          style={{ width: 160 }}
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
      <Table<TenantItem>
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
        title={`租户详情 #${drawerTenant?.id ?? ''}`}
        open={drawerTenant !== null}
        onClose={() => setDrawerTenant(null)}
        width={460}
      >
        {drawerTenant && (
          <>
            <p>
              <b>创建时间：</b>
              {drawerTenant.create_at ? dayjs(drawerTenant.create_at).format('YYYY-MM-DD HH:mm') : '-'}
            </p>
            <Typography.Title level={5}>改名 / 启停</Typography.Title>
            <Form form={updateForm} layout="vertical" onFinish={onUpdate}>
              <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="enabled" label="启用" valuePropName="checked">
                <Switch disabled={drawerTenant.is_primary} />
              </Form.Item>
              <Button type="primary" htmlType="submit">
                保存
              </Button>
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
              <Button type="primary" htmlType="submit">
                提交
              </Button>
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
