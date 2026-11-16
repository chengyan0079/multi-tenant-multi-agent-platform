import { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import {
  addAgentModel,
  bindAgentTenant,
  createAgent,
  deleteAgent,
  listAgentModels,
  listAgents,
  listAgentTenants,
  removeAgentModel,
  setAgentEnabled,
  unbindAgentTenant,
  updateAgent,
  type AgentItem,
  type AgentModelBinding,
} from '../services/agents';
import { listTenants, type TenantItem } from '../services/rbac';
import { listModels, type ModelItem } from '../services/models';
import { hasScope } from '../services/auth';

const PAGE_SIZE = 20;

export default function Agents() {
  const [items, setItems] = useState<AgentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<string | null>(null);

  const [tenants, setTenants] = useState<TenantItem[]>([]);

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [editOpen, setEditOpen] = useState(false);
  const [editForm] = Form.useForm();
  const [editTarget, setEditTarget] = useState<AgentItem | null>(null);

  // 绑定租户
  const [bindOpen, setBindOpen] = useState(false);
  const [bindAgent, setBindAgent] = useState<AgentItem | null>(null);
  const [boundTenants, setBoundTenants] = useState<number[]>([]);
  const [bindTenantId, setBindTenantId] = useState<number | undefined>();

  // 模型绑定
  const [modelOpen, setModelOpen] = useState(false);
  const [modelAgent, setModelAgent] = useState<AgentItem | null>(null);
  const [bindings, setBindings] = useState<AgentModelBinding[]>([]);
  const [models, setModels] = useState<ModelItem[]>([]);
  const [modelForm] = Form.useForm();

  const canAdd = hasScope('agent:add');
  const canUpdate = hasScope('agent:update');
  const canDelete = hasScope('agent:delete');
  const canStatus = hasScope('agent:status');

  const tenantLabel = (id: number) => tenants.find((t) => t.id === id)?.name ?? `#${id}`;

  const load = async (targetPage = page) => {
    setLoading(true);
    try {
      const res = await listAgents({ page: targetPage, page_size: PAGE_SIZE });
      setItems(res?.items ?? []);
      setTotal(res?.total ?? 0);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  useEffect(() => {
    listTenants({ page_size: 200 })
      .then((r) => setTenants(r.items))
      .catch(() => setTenants([]));
  }, []);

  const toggle = async (row: AgentItem, enabled: boolean) => {
    setPending(row.agent_type);
    try {
      await setAgentEnabled(row.agent_type, enabled, row.tenant_id);
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  };

  const openCreate = () => {
    createForm.resetFields();
    createForm.setFieldsValue({ version: '1.0.0', input_schema: '' });
    setCreateOpen(true);
  };

  const submitCreate = async () => {
    const v = await createForm.validateFields();
    const schema = (v.input_schema as string | undefined)?.trim();
    if (schema) {
      try {
        JSON.parse(schema);
      } catch {
        message.error('input_schema 不是合法 JSON');
        return;
      }
    }
    try {
      await createAgent({
        tenant_id: v.tenant_id,
        agent_type: (v.agent_type as string).trim(),
        name: (v.name as string).trim(),
        description: (v.description as string | undefined) ?? '',
        version: (v.version as string | undefined) || '1.0.0',
        input_schema: schema || null,
      });
      message.success('新增成功');
      setCreateOpen(false);
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const openEdit = (row: AgentItem) => {
    setEditTarget(row);
    editForm.resetFields();
    editForm.setFieldsValue({
      tenant_id: row.tenant_id,
      agent_type: row.agent_type,
      name: row.name,
      version: row.version,
      description: row.description ?? '',
      input_schema: row.input_schema ? JSON.stringify(row.input_schema, null, 2) : '',
    });
    setEditOpen(true);
  };

  const submitEdit = async () => {
    if (!editTarget) return;
    const v = await editForm.validateFields();
    const schema = (v.input_schema as string | undefined)?.trim();
    if (schema) {
      try {
        JSON.parse(schema);
      } catch {
        message.error('input_schema 不是合法 JSON');
        return;
      }
    }
    try {
      await updateAgent(editTarget.agent_type, {
        tenant_id: v.tenant_id,
        agent_type: editTarget.agent_type,
        name: (v.name as string).trim(),
        description: (v.description as string | undefined) ?? '',
        version: (v.version as string | undefined) || '1.0.0',
        input_schema: schema || null,
      });
      message.success('更新成功');
      setEditOpen(false);
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const onDelete = async (row: AgentItem) => {
    try {
      await deleteAgent(row.agent_type, row.tenant_id);
      message.success('已删除');
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  // ---------- 绑定租户 ----------
  const openBind = async (row: AgentItem) => {
    setBindAgent(row);
    setBindTenantId(undefined);
    setBindOpen(true);
    try {
      setBoundTenants(await listAgentTenants(row.agent_type));
    } catch {
      setBoundTenants([]);
    }
  };

  const doBind = async () => {
    if (!bindAgent || !bindTenantId) return;
    try {
      await bindAgentTenant(bindAgent.agent_type, bindTenantId);
      message.success('已绑定');
      setBoundTenants(await listAgentTenants(bindAgent.agent_type));
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const doUnbind = async (tid: number) => {
    if (!bindAgent) return;
    try {
      await unbindAgentTenant(bindAgent.agent_type, tid);
      message.success('已解绑');
      setBoundTenants(await listAgentTenants(bindAgent.agent_type));
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  // ---------- 模型绑定 ----------
  const openModels = async (row: AgentItem) => {
    setModelAgent(row);
    setModelOpen(true);
    modelForm.resetFields();
    try {
      const [mb, ms] = await Promise.all([
        listAgentModels(row.agent_type, row.tenant_id, { page_size: 100 }),
        listModels({ page_size: 200 }),
      ]);
      setBindings(mb?.items ?? []);
      setModels(ms?.items ?? []);
    } catch {
      setBindings([]);
    }
  };

  const doAddModel = async () => {
    if (!modelAgent) return;
    const v = await modelForm.validateFields();
    try {
      await addAgentModel(modelAgent.agent_type, modelAgent.tenant_id, {
        model_id: v.model_id,
        is_default: Boolean(v.is_default),
        priority: Number(v.priority) || 0,
      });
      message.success('已绑定模型');
      const mb = await listAgentModels(modelAgent.agent_type, modelAgent.tenant_id, {
        page_size: 100,
      });
      setBindings(mb?.items ?? []);
      modelForm.resetFields();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const doRemoveModel = async (modelId: number) => {
    if (!modelAgent) return;
    try {
      await removeAgentModel(modelAgent.agent_type, modelAgent.tenant_id, modelId);
      message.success('已解绑');
      const mb = await listAgentModels(modelAgent.agent_type, modelAgent.tenant_id, {
        page_size: 100,
      });
      setBindings(mb?.items ?? []);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const columns: ColumnsType<AgentItem> = [
    {
      title: '租户',
      dataIndex: 'tenant_id',
      width: 140,
      render: (id: number) => tenantLabel(id),
    },
    { title: 'Agent 类型', dataIndex: 'agent_type', width: 140 },
    { title: '名称', dataIndex: 'name' },
    { title: '版本', dataIndex: 'version', width: 100 },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 120,
      render: (_: unknown, row: AgentItem) => (
        <Space size={4}>
          <Tag color={row.enabled ? 'green' : 'default'}>{row.enabled ? '启用' : '停用'}</Tag>
          <Switch
            size="small"
            checked={row.enabled}
            disabled={!canStatus}
            loading={pending === row.agent_type}
            onChange={(checked) => void toggle(row, checked)}
          />
        </Space>
      ),
    },
    {
      title: '注册状态',
      dataIndex: 'registered',
      width: 100,
      render: (v: boolean) => (v ? <Tag color="blue">已注册</Tag> : <Tag>未注册</Tag>),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 170,
      render: (v: string | null) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 300,
      render: (_: unknown, row: AgentItem) => (
        <Space size={4}>
          {canUpdate && (
            <Button type="link" size="small" onClick={() => openEdit(row)}>
              编辑
            </Button>
          )}
          <Button type="link" size="small" onClick={() => void openBind(row)}>
            绑定租户
          </Button>
          <Button type="link" size="small" onClick={() => void openModels(row)}>
            配置模型
          </Button>
          {canDelete && (
            <Popconfirm title="确认删除该租户的此 Agent？" onConfirm={() => void onDelete(row)}>
              <Button type="link" size="small" danger>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Card title="智能体管理" extra={canAdd ? <Button type="primary" onClick={openCreate}>新增注册</Button> : null}>
      <Table
        rowKey={(r) => `${r.tenant_id}-${r.agent_type}`}
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          onChange: setPage,
          showSizeChanger: false,
        }}
        scroll={{ x: 'max-content' }}
      />

      <Modal
        title="新增注册"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => void submitCreate()}
        okText="创建"
        destroyOnClose
      >
        <Form form={createForm} layout="vertical">
          <Form.Item name="tenant_id" label="归属租户" rules={[{ required: true }]}>
            <Select options={tenants.map((t) => ({ value: t.id, label: t.name }))} />
          </Form.Item>
          <Form.Item name="agent_type" label="Agent 类型" rules={[{ required: true }]}>
            <Input placeholder="如 qa" />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input />
          </Form.Item>
          <Form.Item name="version" label="版本" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="input_schema" label="输入 schema（JSON，可空）">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`编辑 ${editTarget?.agent_type ?? ''}`}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={() => void submitEdit()}
        okText="保存"
        destroyOnClose
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="tenant_id" label="归属租户">
            <InputNumber disabled style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="agent_type" label="Agent 类型">
            <Input disabled />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input />
          </Form.Item>
          <Form.Item name="version" label="版本" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="input_schema" label="输入 schema（JSON，可空）">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`绑定租户 ${bindAgent?.agent_type ?? ''}`}
        open={bindOpen}
        onCancel={() => setBindOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space.Compact style={{ width: '100%' }}>
            <Select
              style={{ flex: 1 }}
              placeholder="选择租户"
              value={bindTenantId}
              onChange={setBindTenantId}
              options={tenants.map((t) => ({ value: t.id, label: t.name }))}
            />
            <Button type="primary" onClick={() => void doBind()}>
              绑定
            </Button>
          </Space.Compact>
          <div>
            已绑定租户：
            {boundTenants.length === 0 ? (
              <span>无</span>
            ) : (
              <Space wrap>
                {boundTenants.map((tid) => (
                  <Tag
                    key={tid}
                    closable
                    onClose={() => void doUnbind(tid)}
                  >
                    {tenantLabel(tid)}
                  </Tag>
                ))}
              </Space>
            )}
          </div>
        </Space>
      </Modal>

      <Modal
        title={`配置模型 ${modelAgent?.agent_type ?? ''}`}
        open={modelOpen}
        onCancel={() => setModelOpen(false)}
        footer={null}
        width={640}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Form form={modelForm} layout="inline">
            <Form.Item name="model_id" rules={[{ required: true }]}>
              <Select
                style={{ width: 220 }}
                placeholder="选择模型"
                options={models.map((m) => ({ value: m.id, label: `${m.name}（${m.model_type}）` }))}
              />
            </Form.Item>
            <Form.Item name="priority" initialValue={0}>
              <InputNumber min={0} placeholder="优先级" />
            </Form.Item>
            <Form.Item name="is_default" valuePropName="checked" initialValue={false}>
              <Switch checkedChildren="默认" unCheckedChildren="普通" />
            </Form.Item>
            <Button type="primary" onClick={() => void doAddModel()}>
              添加
            </Button>
          </Form>
          <Table
            rowKey="model_id"
            size="small"
            pagination={false}
            dataSource={bindings}
            columns={[
              { title: '模型', dataIndex: 'name' },
              { title: '类型', dataIndex: 'model_type', width: 110 },
              { title: '默认', dataIndex: 'is_default', width: 80, render: (v: boolean) => (v ? '是' : '-') },
              { title: '优先级', dataIndex: 'priority', width: 80 },
              {
                title: '操作',
                width: 90,
                render: (_: unknown, r: AgentModelBinding) => (
                  <Popconfirm title="解绑？" onConfirm={() => void doRemoveModel(r.model_id)}>
                    <Button type="link" size="small" danger>
                      解绑
                    </Button>
                  </Popconfirm>
                ),
              },
            ]}
          />
        </Space>
      </Modal>
    </Card>
  );
}
