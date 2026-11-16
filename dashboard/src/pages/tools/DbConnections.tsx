import { useCallback, useRef, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Tag,
} from 'antd';
import { ProTable, type ActionType, type ProColumns } from '../../components/ProTable';
import dayjs from 'dayjs';

import {
  createDbConnection,
  deleteDbConnection,
  listDbConnections,
  setDbConnectionEnabled,
  testDbConnection,
  updateDbConnection,
  type DbConnectionItem,
  type DbConnectionPayload,
} from '../../services/dbConnections';
import { hasScope } from '../../services/auth';

const DB_TYPES = [
  { value: 'postgresql', label: 'PostgreSQL' },
  { value: 'mysql', label: 'MySQL' },
];

const DEFAULT_FORM: Partial<DbConnectionPayload> = {
  db_type: 'postgresql',
  port: 5432,
  readonly: true,
  enabled: true,
};

export default function DbConnections() {
  const { message } = AntdApp.useApp();
  const actionRef = useRef<ActionType>();

  const canPage = hasScope('db_connection:page');
  const canAdd = hasScope('db_connection:add');
  const canUpdate = hasScope('db_connection:update');
  const canDelete = hasScope('db_connection:delete');
  const canStatus = hasScope('db_connection:status');

  const [createForm] = Form.useForm<DbConnectionPayload>();
  const [editForm] = Form.useForm<DbConnectionPayload>();
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<DbConnectionItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const request = useCallback(async (params: any) => {
    const res = await listDbConnections({
      name: params.name || undefined,
      page: params.current ?? 1,
      page_size: params.pageSize ?? 20,
    });
    return { data: res?.items ?? [], success: true, total: res?.total ?? 0 };
  }, []);

  const openCreate = () => {
    createForm.resetFields();
    createForm.setFieldsValue(DEFAULT_FORM);
    setCreateOpen(true);
  };

  const openEdit = (row: DbConnectionItem) => {
    setEditTarget(row);
    editForm.resetFields();
    editForm.setFieldsValue({
      name: row.name,
      db_type: row.db_type,
      host: row.host,
      port: row.port,
      username: row.username,
      password: '',
      database: row.database,
      schema_name: row.schema_name,
      readonly: row.readonly,
      enabled: row.enabled,
      remark: row.remark,
    });
    setEditOpen(true);
  };

  const onCreate = async (values: DbConnectionPayload) => {
    setSaving(true);
    try {
      await createDbConnection(values);
      message.success('数据源已新增');
      setCreateOpen(false);
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const onEdit = async (values: DbConnectionPayload) => {
    if (!editTarget) return;
    setSaving(true);
    try {
      await updateDbConnection(editTarget.id, values);
      message.success('数据源已更新');
      setEditOpen(false);
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (row: DbConnectionItem, enabled: boolean) => {
    setTogglingId(row.id);
    try {
      await setDbConnectionEnabled(row.id, enabled);
      message.success(enabled ? '已启用' : '已停用');
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setTogglingId(null);
    }
  };

  const onTest = async (row: DbConnectionItem) => {
    setTestingId(row.id);
    try {
      const res = await testDbConnection(row.id);
      if (res.ok) message.success('连接成功');
      else message.error(`连接失败：${res.error ?? '未知错误'}`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setTestingId(null);
    }
  };

  const onDelete = async (row: DbConnectionItem) => {
    try {
      await deleteDbConnection(row.id);
      message.success('数据源已删除');
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const columns: ProColumns<DbConnectionItem>[] = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '类型',
      dataIndex: 'db_type',
      key: 'db_type',
      width: 120,
      search: false,
      render: (_: unknown, row: DbConnectionItem) => <Tag>{row.db_type}</Tag>,
    },
    { title: '主机', dataIndex: 'host', key: 'host', width: 180, search: false },
    { title: '端口', dataIndex: 'port', key: 'port', width: 100, search: false },
    { title: '数据库', dataIndex: 'database', key: 'database', width: 140, search: false },
    { title: 'schema', dataIndex: 'schema_name', key: 'schema_name', width: 120, search: false },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 100,
      search: false,
      render: (_: unknown, row: DbConnectionItem) => (
        <Space size={4}>
          <Tag color={row.enabled ? 'green' : 'default'}>{row.enabled ? '启用' : '停用'}</Tag>
          <Switch
            size="small"
            checked={row.enabled}
            disabled={!canStatus}
            loading={togglingId === row.id}
            onChange={(checked) => void toggle(row, checked)}
          />
        </Space>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'create_at',
      key: 'create_at',
      width: 170,
      search: false,
      render: (v: any) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 220,
      search: false,
      render: (_: unknown, row: DbConnectionItem) => (
        <Space size={4}>
          <Button type="link" size="small" loading={testingId === row.id} onClick={() => void onTest(row)}>
            测试连接
          </Button>
          {canUpdate && (
            <Button type="link" size="small" onClick={() => openEdit(row)}>
              编辑
            </Button>
          )}
          {canDelete && (
            <Popconfirm title="确认删除该数据源？" onConfirm={() => void onDelete(row)}>
              <Button type="link" size="small" danger>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  const renderForm = (form: typeof createForm, onFinish: (v: DbConnectionPayload) => void, editing: boolean) => (
    <Form form={form} layout="vertical" onFinish={onFinish} initialValues={DEFAULT_FORM}>
      <Form.Item name="name" label="名称" rules={[{ required: true }]}>
        <Input placeholder="数据源名（租户内唯一）" disabled={editing} />
      </Form.Item>
      <Form.Item name="db_type" label="类型" rules={[{ required: true }]}>
        <Select options={DB_TYPES} disabled={editing} />
      </Form.Item>
      <Form.Item name="host" label="主机" rules={[{ required: true }]}>
        <Input placeholder="如 10.0.0.1" />
      </Form.Item>
      <Form.Item name="port" label="端口" rules={[{ required: true }]}>
        <InputNumber min={1} max={65535} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
        <Input />
      </Form.Item>
      <Form.Item
        name="password"
        label={editing ? '密码（留空不修改）' : '密码'}
        rules={editing ? [] : [{ required: true }]}
      >
        <Input.Password placeholder={editing ? '不修改请留空' : ''} />
      </Form.Item>
      <Form.Item name="database" label="数据库" rules={[{ required: true }]}>
        <Input />
      </Form.Item>
      <Form.Item name="schema_name" label="schema（PostgreSQL 可选）">
        <Input placeholder="public" />
      </Form.Item>
      <Form.Item name="readonly" label="只读" valuePropName="checked">
        <Switch />
      </Form.Item>
      <Form.Item name="enabled" label="启用" valuePropName="checked">
        <Switch />
      </Form.Item>
      <Form.Item name="remark" label="备注">
        <Input.TextArea rows={2} />
      </Form.Item>
    </Form>
  );

  if (!canPage) {
    return <div style={{ padding: 24 }}>你没有查看数据库管理的权限</div>;
  }

  return (
    <div>
      <ProTable<DbConnectionItem>
        headerTitle="数据库管理列表"
        actionRef={actionRef}
        toolBarRender={() =>
          canAdd
            ? [
                <Button key="add" type="primary" onClick={openCreate}>
                  新增数据源
                </Button>,
              ]
            : []
        }
        rowKey="id"
        columns={columns}
        request={request}
        search={{ labelWidth: 'auto' }}
        options={{ fullScreen: true, setting: true, density: true, reload: true }}
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: true }}
      />

      <Modal
        title="新增数据源"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        confirmLoading={saving}
        okText="创建"
        width={640}
        destroyOnClose
      >
        {renderForm(createForm, (v) => void onCreate(v), false)}
      </Modal>

      <Modal
        title={`编辑数据源 ${editTarget?.name ?? ''}`}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={() => editForm.submit()}
        confirmLoading={saving}
        okText="保存"
        width={640}
        destroyOnClose
      >
        {renderForm(editForm, (v) => void onEdit(v), true)}
      </Modal>
    </div>
  );
}
