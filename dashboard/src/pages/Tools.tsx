import { useCallback, useEffect, useRef, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
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
  createTool,
  deleteTool,
  getTool,
  listTools,
  setToolEnabled,
  updateTool,
  type ToolItem,
  type ToolPayload,
} from '../services/tools';
import { listTenants, type TenantItem } from '../services/rbac';
import { getSession, hasScope } from '../services/auth';

const DEFAULT_FORM: Partial<ToolPayload> = {
  plugin: '',
  description: '',
  schema: '{}',
  config: '{}',
  enabled: true,
};

function parseJson(value: string): string | null {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return null;
  }
}

interface FormValues extends ToolPayload {}

export default function Tools() {
  const { message } = AntdApp.useApp();
  const actionRef = useRef<ActionType>();

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
  const [editTarget, setEditTarget] = useState<ToolItem | null>(null);
  const [drawerTool, setDrawerTool] = useState<ToolItem | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    listTenants({ page_size: 200 })
      .then((r) => setTenantOptions(r.items.map((t: TenantItem) => ({ value: t.id, label: t.name }))))
      .catch(() => setTenantOptions([]));
  }, []);

  const tenantLabel = (id: number): string =>
    tenantOptions.find((o) => o.value === id)?.label ?? `#${id}`;

  // 超管默认查全部租户；租户默认查当前租户
  const session = getSession();
  const isSuperAdmin = session?.isSuperAdmin ?? false;
  const defaultTenant = isSuperAdmin ? undefined : session?.tenant?.id ?? undefined;

  const request = useCallback(
    async (params: any) => {
      const res = await listTools({
        tenant_id: params.tenant_id ? Number(params.tenant_id) : defaultTenant,
        name: params.name || undefined,
        enabled: params.enabled === '' || params.enabled === undefined ? undefined : params.enabled,
        page: params.current ?? 1,
        page_size: params.pageSize ?? 20,
      });
      return { data: res?.items ?? [], success: true, total: res?.total ?? 0 };
    },
    [defaultTenant],
  );

  const buildPayload = (values: FormValues): ToolPayload => ({
    tenant_id: values.tenant_id,
    name: values.name,
    plugin: values.plugin,
    description: values.description,
    schema: values.schema,
    config: values.config,
    enabled: values.enabled,
  });

  const validateJson = (values: FormValues): boolean => {
    for (const field of ['schema', 'config'] as const) {
      if (parseJson(values[field] ?? '') === null) {
        message.error(`${field} 不是合法 JSON`);
        return false;
      }
    }
    return true;
  };

  const openCreate = () => {
    createForm.resetFields();
    createForm.setFieldsValue(DEFAULT_FORM);
    setCreateOpen(true);
  };

  const openEdit = (row: ToolItem) => {
    setEditTarget(row);
    editForm.resetFields();
    editForm.setFieldsValue({
      tenant_id: row.tenant_id,
      name: row.name,
      plugin: row.plugin,
      description: row.description,
      schema: parseJson(row.schema) ?? row.schema,
      config: parseJson(row.config) ?? row.config,
      enabled: row.enabled,
    });
    setEditOpen(true);
  };

  const onCreate = async (values: FormValues) => {
    if (!validateJson(values)) return;
    setSaving(true);
    try {
      await createTool(buildPayload(values));
      message.success('工具已新增');
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
      await updateTool(editTarget.id, buildPayload(values));
      message.success('工具已更新');
      setEditOpen(false);
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (row: ToolItem, enabled: boolean) => {
    setTogglingId(row.id);
    try {
      await setToolEnabled(row.id, enabled);
      message.success(enabled ? '已启用' : '已停用');
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setTogglingId(null);
    }
  };

  const onDelete = async (row: ToolItem) => {
    try {
      await deleteTool(row.id);
      message.success('工具已删除');
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const openDetail = async (id: string) => {
    setDrawerTool(null);
    try {
      setDrawerTool(await getTool(id));
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const columns: ProColumns<ToolItem>[] = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '插件', dataIndex: 'plugin', key: 'plugin', width: 140, search: false },
    { title: '说明', dataIndex: 'description', key: 'description', width: 220, ellipsis: true, search: false },
    {
      title: '租户',
      dataIndex: 'tenant_id',
      key: 'tenant_id',
      width: 140,
      valueType: 'select',
      valueEnum: Object.fromEntries(tenantOptions.map((o) => [o.value, { text: o.label }])),
      render: (_: unknown, row: ToolItem) => tenantLabel(row.tenant_id),
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 110,
      valueType: 'select',
      valueEnum: { true: { text: '启用' }, false: { text: '停用' } },
      render: (_: unknown, row: ToolItem) => (
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
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      search: false,
      render: (value: any) => (value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      search: false,
      render: (_: unknown, row: ToolItem) => (
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
            <Popconfirm title="确认删除该工具？" onConfirm={() => void onDelete(row)}>
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
      <Form.Item name="tenant_id" label="归属租户" rules={[{ required: true }]}>
        <Select options={tenantOptions} disabled={editing} />
      </Form.Item>
      <Form.Item name="name" label="名称" rules={[{ required: true }]}>
        <Input placeholder="工具名（租户内唯一）" disabled={editing} />
      </Form.Item>
      <Form.Item name="plugin" label="插件">
        <Input placeholder="如 web_search" />
      </Form.Item>
      <Form.Item name="description" label="说明">
        <Input />
      </Form.Item>
      <Form.Item name="schema" label="工具 Schema（JSON）" rules={[{ required: true }]}>
        <Input.TextArea rows={3} placeholder="{}" />
      </Form.Item>
      <Form.Item name="config" label="运行配置（JSON，含 api_key/endpoint 等）" rules={[{ required: true }]}>
        <Input.TextArea rows={3} placeholder="{}" />
      </Form.Item>
      <Form.Item name="enabled" label="启用" valuePropName="checked">
        <Switch />
      </Form.Item>
    </Form>
  );

  if (!canPage) {
    return <Result status="403" title="无权限" subTitle="你没有查看工具管理的权限" />;
  }

  return (
    <div>
      <ProTable<ToolItem>
        headerTitle="工具管理"
        actionRef={actionRef}
        toolBarRender={() =>
          canAdd
            ? [
                <Button key="add" type="primary" onClick={openCreate}>
                  新增工具
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
        title="新增工具"
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
        title={`编辑工具 ${editTarget?.name ?? ''}`}
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

      <Drawer title="工具详情" open={drawerTool !== null} onClose={() => setDrawerTool(null)} width={560}>
        {drawerTool && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="ID">{drawerTool.id}</Descriptions.Item>
            <Descriptions.Item label="名称">{drawerTool.name}</Descriptions.Item>
            <Descriptions.Item label="插件">{drawerTool.plugin}</Descriptions.Item>
            <Descriptions.Item label="说明">{drawerTool.description}</Descriptions.Item>
            <Descriptions.Item label="归属租户">{tenantLabel(drawerTool.tenant_id)}</Descriptions.Item>
            <Descriptions.Item label="状态">{drawerTool.enabled ? '启用' : '停用'}</Descriptions.Item>
            <Descriptions.Item label="Schema">
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                {parseJson(drawerTool.schema) ?? drawerTool.schema}
              </pre>
            </Descriptions.Item>
            <Descriptions.Item label="配置">
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                {parseJson(drawerTool.config) ?? drawerTool.config}
              </pre>
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">{drawerTool.create_at}</Descriptions.Item>
            <Descriptions.Item label="更新时间">{drawerTool.updated_at}</Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
}
