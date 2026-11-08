import { useCallback, useEffect, useRef, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Tag,
  Result,
} from 'antd';
import { ProTable, type ActionType, type ProColumns } from '../components/ProTable';
import dayjs from 'dayjs';

import {
  createPlugin,
  deletePlugin,
  getPlugin,
  listPlugins,
  setPluginStatus,
  updatePlugin,
  type PluginItem,
  type PluginPayload,
} from '../services/plugins';
import { listTenants, type TenantItem } from '../services/rbac';
import { hasScope } from '../services/auth';

const STATUS_OPTIONS = [
  { value: 'enabled', label: '启用' },
  { value: 'disabled', label: '停用' },
];

const DEFAULT_FORM = {
  version: '1.0.0',
  capabilities: '[]',
  config: '{}',
  status: 'enabled',
};

function parseJson(value: string): string | null {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return null;
  }
}

interface FormValues extends PluginPayload {}

export default function Tools() {
  const { message } = AntdApp.useApp();
  const actionRef = useRef<ActionType>();

  // 工具/插件权限点（与后端 Scope 对齐）：列表按 page 拦，写操作按各自 scope 拦
  const canPage = hasScope('tool:page');
  const canAdd = hasScope('tool:add');
  const canUpdate = hasScope('tool:update');
  const canDelete = hasScope('tool:delete');
  const canView = hasScope('tool:view');
  const canStatus = hasScope('tool:status');
  const [createForm] = Form.useForm<FormValues>();
  const [editForm] = Form.useForm<FormValues>();

  const [tenantOptions, setTenantOptions] = useState<{ value: number; label: string }[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<PluginItem | null>(null);
  const [drawerPlugin, setDrawerPlugin] = useState<PluginItem | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    listTenants({ page_size: 200 })
      .then((r) => setTenantOptions(r.items.map((t: TenantItem) => ({ value: t.id, label: t.name }))))
      .catch(() => setTenantOptions([]));
  }, []);

  const tenantLabel = (id: number): string =>
    tenantOptions.find((o) => o.value === id)?.label ?? `#${id}`;

  const request = useCallback(async (params: any) => {
    const res = await listPlugins({
      name: params.name || undefined,
      status: params.status || undefined,
      page: params.current ?? 1,
      page_size: params.pageSize ?? 20,
    });
    return { data: res?.items ?? [], success: true, total: res?.total ?? 0 };
  }, []);

  const buildPayload = (values: FormValues): PluginPayload => ({
    name: values.name,
    version: values.version,
    capabilities: values.capabilities,
    config: values.config,
    status: values.status,
    tenant_id: values.tenant_id,
    user_id: values.user_id,
  });

  const validateJson = (values: FormValues): boolean => {
    for (const field of ['capabilities', 'config'] as const) {
      if (parseJson(values[field]) === null) {
        message.error(`${field} 不是合法 JSON`);
        return false;
      }
    }
    return true;
  };

  const openCreate = () => {
    createForm.resetFields();
    createForm.setFieldsValue(DEFAULT_FORM as FormValues);
    setCreateOpen(true);
  };

  const openEdit = (row: PluginItem) => {
    setEditTarget(row);
    editForm.resetFields();
    editForm.setFieldsValue({
      name: row.name,
      version: row.version,
      capabilities: parseJson(row.capabilities) ?? row.capabilities,
      config: parseJson(row.config) ?? row.config,
      status: row.status,
      tenant_id: row.tenant_id,
      user_id: row.user_id,
    });
    setEditOpen(true);
  };

  const onCreate = async (values: FormValues) => {
    if (!validateJson(values)) return;
    setSaving(true);
    try {
      await createPlugin(buildPayload(values));
      message.success('插件已新增');
      setCreateOpen(false);
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const onEdit = async (values: FormValues) => {
    if (!editTarget || !validateJson(values)) return;
    setSaving(true);
    try {
      await updatePlugin(editTarget.id, buildPayload(values));
      message.success('插件已更新');
      setEditOpen(false);
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (row: PluginItem, enabled: boolean) => {
    setTogglingId(row.id);
    try {
      await setPluginStatus(row.id, enabled ? 'enabled' : 'disabled');
      message.success(enabled ? '已启用' : '已停用');
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setTogglingId(null);
    }
  };

  const onDelete = async (row: PluginItem) => {
    try {
      await deletePlugin(row.id);
      message.success('插件已删除');
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const openDetail = async (id: string) => {
    setDrawerPlugin(null);
    try {
      setDrawerPlugin(await getPlugin(id));
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const columns: ProColumns<PluginItem>[] = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '版本', dataIndex: 'version', key: 'version', width: 100, search: false },
    {
      title: '租户',
      dataIndex: 'tenant_id',
      key: 'tenant_id',
      width: 140,
      search: false,
      render: (_: unknown, row: PluginItem) => tenantLabel(row.tenant_id),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      valueType: 'select',
      valueEnum: { enabled: { text: '启用' }, disabled: { text: '停用' } },
      render: (_: unknown, row: PluginItem) => (
        <Space size={4}>
          <Tag color={row.status === 'enabled' ? 'green' : 'default'}>
            {row.status === 'enabled' ? '启用' : '停用'}
          </Tag>
          <Switch
            size="small"
            checked={row.status === 'enabled'}
            disabled={!canStatus}
            loading={togglingId === row.id}
            onChange={(checked) => void toggle(row, checked)}
          />
        </Space>
      ),
    },
    {
      title: '注册时间',
      dataIndex: 'registered_at',
      key: 'registered_at',
      width: 170,
      search: false,
      render: (value: any) => (value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      search: false,
      render: (_: unknown, row: PluginItem) => (
        <Space size={4}>
          {canView && (
            <Button type="link" size="small" onClick={() => void openDetail(row.id)}>
              详情
            </Button>
          )}
          {canUpdate && (
            <Button type="link" size="small" onClick={() => openEdit(row)}>
              编辑
            </Button>
          )}
          {canDelete && (
            <Popconfirm title="确认删除该插件？" onConfirm={() => void onDelete(row)}>
              <Button type="link" size="small" danger>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  const renderForm = (form: typeof createForm, onFinish: (v: FormValues) => void, editing: boolean) => (
    <Form form={form} layout="vertical" onFinish={onFinish} initialValues={DEFAULT_FORM}>
      <Form.Item name="name" label="名称" rules={[{ required: true }]}>
        <Input placeholder="插件名，全局唯一" disabled={editing} />
      </Form.Item>
      <Form.Item name="version" label="版本" rules={[{ required: true }]}>
        <Input placeholder="如 1.0.0" />
      </Form.Item>
      <Form.Item name="status" label="状态" rules={[{ required: true }]}>
        <Select options={STATUS_OPTIONS} />
      </Form.Item>
      <Form.Item name="tenant_id" label="归属租户" rules={[{ required: true }]}>
        <Select options={tenantOptions} disabled={editing} />
      </Form.Item>
      <Form.Item name="user_id" label="维护人 ID" rules={[{ required: true }]}>
        <InputNumber min={1} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name="capabilities" label="能力列表（JSON）" rules={[{ required: true }]}>
        <Input.TextArea rows={3} placeholder='["web_search"]' />
      </Form.Item>
      <Form.Item name="config" label="配置（JSON）" rules={[{ required: true }]}>
        <Input.TextArea rows={3} placeholder="{}" />
      </Form.Item>
    </Form>
  );

  if (!canPage) {
    return <Result status="403" title="无权限" subTitle="你没有查看工具与插件的权限" />;
  }

  return (
    <div>
      <ProTable<PluginItem>
        headerTitle="工具与插件"
        actionRef={actionRef}
        toolBarRender={() =>
          canAdd
            ? [
                <Button key="add" type="primary" onClick={openCreate}>
                  新增插件
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
        title="新增插件"
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
        title={`编辑插件 ${editTarget?.name ?? ''}`}
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

      <Drawer
        title="插件详情"
        open={drawerPlugin !== null}
        onClose={() => setDrawerPlugin(null)}
        width={560}
      >
        {drawerPlugin && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="ID">{drawerPlugin.id}</Descriptions.Item>
            <Descriptions.Item label="名称">{drawerPlugin.name}</Descriptions.Item>
            <Descriptions.Item label="版本">{drawerPlugin.version}</Descriptions.Item>
            <Descriptions.Item label="状态">{drawerPlugin.status}</Descriptions.Item>
            <Descriptions.Item label="归属租户">{tenantLabel(drawerPlugin.tenant_id)}</Descriptions.Item>
            <Descriptions.Item label="维护人 ID">{drawerPlugin.user_id}</Descriptions.Item>
            <Descriptions.Item label="能力列表">
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                {parseJson(drawerPlugin.capabilities) ?? drawerPlugin.capabilities}
              </pre>
            </Descriptions.Item>
            <Descriptions.Item label="配置">
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                {parseJson(drawerPlugin.config) ?? drawerPlugin.config}
              </pre>
            </Descriptions.Item>
            <Descriptions.Item label="注册时间">{drawerPlugin.registered_at}</Descriptions.Item>
            <Descriptions.Item label="更新时间">{drawerPlugin.updated_at}</Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
}
