import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
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
  Table,
  Tag,
  Tooltip,
  Typography,
  Result,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ProTable, type ProColumns } from '../components/ProTable';
import dayjs from 'dayjs';

import {
  addAgentModel,
  createAgent,
  deleteAgent,
  listAgentModels,
  listAgents,
  listCapabilities,
  removeAgentModel,
  setAgentEnabled,
  setCapabilities,
  updateAgent,
  updateAgentModel,
  type AgentItem,
  type AgentModelBinding,
  type CapabilityItem,
} from '../services/agents';
import { listTenants, type TenantItem } from '../services/rbac';
import { MODEL_TYPES, listModels, type ModelItem } from '../services/models';
import { sortByTimeThenId } from '../utils/sort';
import { hasScope } from '../services/auth';

export default function Agents() {
  const [items, setItems] = useState<AgentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [deletePending, setDeletePending] = useState<string | null>(null);

  // 新增 / 编辑（独立弹窗与表单）
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [editOpen, setEditOpen] = useState(false);
  const [editForm] = Form.useForm();
  const [editTarget, setEditTarget] = useState<AgentItem | null>(null);

  // 模型绑定配置 Drawer
  const [configOpen, setConfigOpen] = useState(false);
  const [configAgent, setConfigAgent] = useState<AgentItem | null>(null);
  const [bindings, setBindings] = useState<AgentModelBinding[]>([]);
  const [bindLoading, setBindLoading] = useState(false);
  const [models, setModels] = useState<ModelItem[]>([]);
  const [addForm] = Form.useForm();
  const [addLoading, setAddLoading] = useState(false);
  const [bindPending, setBindPending] = useState<string | null>(null);

  // 详情 / 租户开通策略
  const [detailRow, setDetailRow] = useState<AgentItem | null>(null);
  const [policyOpen, setPolicyOpen] = useState(false);
  const [tenants, setTenants] = useState<TenantItem[]>([]);
  const [policyTenantId, setPolicyTenantId] = useState<number | null>(null);
  const [capabilities, setCapList] = useState<CapabilityItem[]>([]);
  const [capLoading, setCapLoading] = useState(false);
  const [capSaving, setCapSaving] = useState(false);

  // 智能体管理权限点（与后端 Scope 对齐）：列表按 page 拦，写操作按各自 scope 拦
  const canPage = hasScope('agent:page');
  const canAdd = hasScope('agent:add');
  const canUpdate = hasScope('agent:update');
  const canDelete = hasScope('agent:delete');
  const canStatus = hasScope('agent:status');

  const load = async (targetPage = page, targetPageSize = pageSize) => {
    setLoading(true);
    setError(null);
    try {
      const res = await listAgents({ page: targetPage, page_size: targetPageSize });
      setItems(sortByTimeThenId(res?.items ?? []));
      setTotal(res?.total ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(page, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize]);

  const toggle = async (agentType: string, enabled: boolean) => {
    setPending(agentType);
    try {
      await setAgentEnabled(agentType, enabled);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  };

  // ---------- 新增 ----------
  const openCreate = () => {
    createForm.resetFields();
    createForm.setFieldsValue({ version: '1.0.0', enabled: true, input_schema: '' });
    setCreateOpen(true);
  };

  const submitCreate = async () => {
    const values = await createForm.validateFields();
    const schema = (values.input_schema as string | undefined)?.trim();
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
        agent_type: (values.agent_type as string).trim(),
        name: (values.name as string).trim(),
        description: (values.description as string | undefined) ?? '',
        version: (values.version as string | undefined) || '1.0.0',
        enabled: Boolean(values.enabled),
        input_schema: schema || null,
      });
      message.success('新增成功');
      setCreateOpen(false);
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  // ---------- 编辑 ----------
  const openEdit = (row: AgentItem) => {
    setEditTarget(row);
    editForm.resetFields();
    editForm.setFieldsValue({
      agent_type: row.agent_type,
      name: row.name,
      version: row.version,
      description: row.description ?? '',
      enabled: row.enabled,
      input_schema: row.input_schema ? JSON.stringify(row.input_schema, null, 2) : '',
    });
    setEditOpen(true);
  };

  const submitEdit = async () => {
    if (!editTarget) return;
    const values = await editForm.validateFields();
    const schema = (values.input_schema as string | undefined)?.trim();
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
        agent_type: editTarget.agent_type,
        name: (values.name as string).trim(),
        description: (values.description as string | undefined) ?? '',
        version: (values.version as string | undefined) || '1.0.0',
        enabled: Boolean(values.enabled),
        input_schema: schema || null,
      });
      message.success('更新成功');
      setEditOpen(false);
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  // ---------- 删除（有绑定则禁止） ----------
  const doDelete = async (row: AgentItem) => {
    setDeletePending(row.agent_type);
    try {
      const res = await listAgentModels(row.agent_type, { page_size: 1 });
      if ((res?.total ?? 0) > 0) {
        message.error('该智能体已绑定模型，请先到「配置」解绑后再删除');
        return;
      }
      await deleteAgent(row.agent_type);
      message.success('已删除');
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setDeletePending(null);
    }
  };

  // ---------- 模型绑定配置 ----------
  const loadBindings = async (agentType: string) => {
    setBindLoading(true);
    try {
      const res = await listAgentModels(agentType, { page_size: 200 });
      setBindings(res?.items ?? []);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBindLoading(false);
    }
  };

  const loadModels = async () => {
    try {
      const res = await listModels({ page_size: 200 });
      setModels(res?.items ?? []);
    } catch {
      // 模型列表拉取失败不阻断绑定列表展示
    }
  };

  const openConfig = (row: AgentItem) => {
    setConfigAgent(row);
    setBindings([]);
    addForm.resetFields();
    addForm.setFieldsValue({ is_default: false, priority: 0 });
    setConfigOpen(true);
    void loadBindings(row.agent_type);
    void loadModels();
  };

  const submitAddBinding = async () => {
    if (!configAgent) return;
    const values = await addForm.validateFields();
    setAddLoading(true);
    try {
      await addAgentModel(configAgent.agent_type, {
        model_id: values.model_id as number,
        is_default: Boolean(values.is_default),
        priority: Number(values.priority ?? 0),
      });
      message.success('已添加绑定');
      addForm.resetFields();
      addForm.setFieldsValue({ is_default: false, priority: 0 });
      await loadBindings(configAgent.agent_type);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setAddLoading(false);
    }
  };

  const setDefaultBinding = async (modelId: number) => {
    if (!configAgent) return;
    const key = `${configAgent.agent_type}-${modelId}`;
    setBindPending(key);
    try {
      await updateAgentModel(configAgent.agent_type, modelId, { is_default: true });
      message.success('已设为默认');
      await loadBindings(configAgent.agent_type);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBindPending(null);
    }
  };

  const removeBinding = async (modelId: number) => {
    if (!configAgent) return;
    const key = `${configAgent.agent_type}-${modelId}`;
    setBindPending(key);
    try {
      await removeAgentModel(configAgent.agent_type, modelId);
      message.success('已解绑');
      await loadBindings(configAgent.agent_type);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBindPending(null);
    }
  };

  // 模型下拉按 model_type 分组
  const modelOptions = useMemo(() => {
    const byType: Record<string, { label: string; value: number }[]> = {};
    for (const m of models) {
      (byType[m.model_type] ??= []).push({
        label: `${m.name}${m.provider ? ` · ${m.provider}` : ''}${m.enabled ? '' : '（已停用）'}`,
        value: m.id,
      });
    }
    return Object.entries(byType).map(([type, options]) => ({
      label: MODEL_TYPES.find((t) => t.value === type)?.label ?? type,
      options,
    }));
  }, [models]);

  // ---------- 详情 / 租户开通策略 ----------
  const openDetail = (row: AgentItem) => setDetailRow(row);

  const openPolicy = async () => {
    setPolicyOpen(true);
    if (!tenants.length) {
      try {
        const res = await listTenants({ page: 1, page_size: 200 });
        setTenants(res.items ?? []);
      } catch (e) {
        message.error(e instanceof Error ? e.message : String(e));
      }
    }
  };

  const loadCapabilities = async (tenantId: number) => {
    setCapLoading(true);
    try {
      const res = await listCapabilities(tenantId, { page: 1, page_size: 200 });
      setCapList(res.items ?? []);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setCapLoading(false);
    }
  };

  const onSelectTenant = (tenantId: number) => {
    setPolicyTenantId(tenantId);
    setCapList([]);
    void loadCapabilities(tenantId);
  };

  const toggleCapability = (agentType: string, enabled: boolean) => {
    setCapList((prev) =>
      prev.map((c) => (c.agent_type === agentType ? { ...c, enabled, configured: true } : c)),
    );
  };

  const saveCapabilities = async () => {
    if (policyTenantId == null) return;
    setCapSaving(true);
    try {
      await setCapabilities(
        policyTenantId,
        capabilities.map((c) => ({ agent_type: c.agent_type, enabled: c.enabled })),
      );
      message.success('租户开通策略已保存');
      await loadCapabilities(policyTenantId);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setCapSaving(false);
    }
  };

  const columns: ColumnsType<AgentItem> = [
    { title: '智能体', dataIndex: 'name', key: 'name' },
    { title: '类型', dataIndex: 'agent_type', key: 'agent_type' },
    { title: '版本', dataIndex: 'version', key: 'version' },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      render: (value: boolean, row: AgentItem) => {
        if (!row.registered) return <Tag>未接入</Tag>;
        return <Tag color={value ? 'green' : 'orange'}>{value ? '运行中' : '已停用'}</Tag>;
      },
    },
    {
      title: '代码接入',
      dataIndex: 'registered',
      key: 'registered',
      render: (value: boolean) => (
        <Tooltip title="是否已在代码中实现并注册到 AgentRegistry；未接入的仅库登记，启停不影响运行">
          <Tag color={value ? 'blue' : 'default'}>{value ? '已接入' : '未接入'}</Tag>
        </Tooltip>
      ),
    },
    { title: '说明', dataIndex: 'description', key: 'description' },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (v: string | null) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '启停',
      key: 'enabled_switch',
      width: 80,
      render: (_: unknown, row: AgentItem) => (
        <Tooltip title={row.registered ? '' : '代码未接入，启停不影响运行'}>
          <Switch
            checked={row.enabled}
            disabled={!row.registered || !canStatus}
            loading={pending === row.agent_type}
            onChange={(checked) => void toggle(row.agent_type, checked)}
          />
        </Tooltip>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 220,
      render: (_: unknown, row: AgentItem) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => openDetail(row)}>
            详情
          </Button>
          {canUpdate && (
            <Button type="link" size="small" onClick={() => openConfig(row)}>
              配置
            </Button>
          )}
          {canUpdate && (
            <Button type="link" size="small" onClick={() => openEdit(row)}>
              编辑
            </Button>
          )}
          {canDelete && (
            <Popconfirm
              title={`确认删除「${row.name}」？`}
              description="删除后不可恢复；已绑定模型的需先解绑。"
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => doDelete(row)}
            >
              <Button
                type="link"
                size="small"
                danger
                loading={deletePending === row.agent_type}
              >
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  const bindingColumns: ColumnsType<AgentModelBinding> = [
    {
      title: '模型类型',
      dataIndex: 'model_type',
      key: 'model_type',
      render: (v: string) => MODEL_TYPES.find((t) => t.value === v)?.label ?? v,
    },
    {
      title: '模型',
      key: 'model',
      render: (_: unknown, row) => (
        <span>
          {row.name}
          {row.provider ? <Typography.Text type="secondary"> · {row.provider}</Typography.Text> : null}
        </span>
      ),
    },
    {
      title: '默认',
      dataIndex: 'is_default',
      key: 'is_default',
      render: (v: boolean) => <Tag color={v ? 'green' : 'default'}>{v ? '默认' : '候选'}</Tag>,
    },
    { title: '优先级', dataIndex: 'priority', key: 'priority', width: 90 },
    {
      title: '模型状态',
      dataIndex: 'model_enabled',
      key: 'model_enabled',
      render: (v: boolean) => <Tag color={v ? 'blue' : 'red'}>{v ? '启用' : '停用'}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_: unknown, row) => (
        <Space size="small">
          {!row.is_default && canUpdate && (
            <Button
              type="link"
              size="small"
              loading={bindPending === `${configAgent?.agent_type}-${row.model_id}`}
              onClick={() => void setDefaultBinding(row.model_id)}
            >
              设默认
            </Button>
          )}
          {canDelete && (
            <Popconfirm
              title="确认解绑该模型？"
              okText="解绑"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => removeBinding(row.model_id)}
            >
              <Button
                type="link"
                size="small"
                danger
                loading={bindPending === `${configAgent?.agent_type}-${row.model_id}`}
              >
                解绑
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  if (!canPage) {
    return <Result status="403" title="无权限" subTitle="你没有查看智能体管理的权限" />;
  }

  return (
    <Card
      title={<Typography.Title level={4} style={{ margin: 0 }}>智能体列表</Typography.Title>}
      extra={
        <Space>
          <Button disabled={!canUpdate} onClick={() => void openPolicy()}>
            租户开通策略
          </Button>
          <Button type="primary" disabled={!canAdd} onClick={openCreate}>
            新增智能体
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        {error && <Alert type="error" showIcon message={`加载失败：${error}`} />}
        <ProTable<AgentItem>
          search={false}
          options={{ fullScreen: true, setting: true, density: true, reload: false }}
          rowKey="agent_type"
          columns={columns as ProColumns<AgentItem>[]}
          dataSource={items}
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            onChange: (next, size) => {
              setPage(next);
              setPageSize(size);
            },
          }}
          scroll={{ x: 'max-content' }}
        />
      </Space>

      {/* 新增 */}
      <Modal
        title="新增智能体"
        open={createOpen}
        onOk={() => void submitCreate()}
        onCancel={() => setCreateOpen(false)}
        okText="保存"
        cancelText="取消"
        forceRender
      >
        <Form form={createForm} layout="vertical">
          <Form.Item
            name="agent_type"
            label="Agent 类型"
            rules={[{ required: true, message: '请输入 agent_type' }]}
            extra="业务唯一键；未在代码中注册的将显示为「仅库登记」，运行时不生效。"
          >
            <Input placeholder="如 knowledge_qa" maxLength={64} />
          </Form.Item>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item name="version" label="版本">
            <Input placeholder="1.0.0" maxLength={32} />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="enabled" label="全局启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item
            name="input_schema"
            label="输入 Schema（JSON，可空）"
            extra="留空表示无；填写需为合法 JSON。"
          >
            <Input.TextArea rows={4} placeholder='{"type":"object","properties":{}}' />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑 */}
      <Modal
        title={`编辑智能体${editTarget ? ` · ${editTarget.name}` : ''}`}
        open={editOpen}
        onOk={() => void submitEdit()}
        onCancel={() => setEditOpen(false)}
        okText="保存"
        cancelText="取消"
        forceRender
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="agent_type" label="Agent 类型">
            <Input disabled />
          </Form.Item>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item name="version" label="版本">
            <Input maxLength={32} />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="enabled" label="全局启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item
            name="input_schema"
            label="输入 Schema（JSON，可空）"
            extra="留空表示无；填写需为合法 JSON。"
          >
            <Input.TextArea rows={4} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 模型绑定配置 */}
      <Drawer
        title={`模型绑定 · ${configAgent?.name ?? ''}`}
        width={760}
        open={configOpen}
        onClose={() => setConfigOpen(false)}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Typography.Text type="secondary">
            一个智能体可按模型类型绑定多个模型；同类仅一个默认项，运行时优先使用默认项。
          </Typography.Text>
          <Table<AgentModelBinding>
            size="small"
            rowKey={(row) => `${row.agent_id}-${row.model_id}`}
            columns={bindingColumns}
            dataSource={bindings}
            loading={bindLoading}
            pagination={false}
            locale={{ emptyText: '暂无绑定，请在下方添加' }}
          />
          <Typography.Title level={5} style={{ margin: '8px 0 0' }}>
            添加绑定
          </Typography.Title>
          <Form form={addForm} layout="inline" initialValues={{ is_default: false, priority: 0 }}>
            <Form.Item
              name="model_id"
              label="模型"
              rules={[{ required: true, message: '请选择模型' }]}
              style={{ minWidth: 260 }}
            >
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="选择模型"
                options={modelOptions}
              />
            </Form.Item>
            <Form.Item name="is_default" label="设为默认" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="priority" label="优先级">
              <InputNumber min={0} />
            </Form.Item>
            <Form.Item>
              <Button type="primary" loading={addLoading} disabled={!canUpdate} onClick={() => void submitAddBinding()}>
                添加
              </Button>
            </Form.Item>
          </Form>
        </Space>
      </Drawer>

      {/* 详情 */}
      <Drawer
        title={`智能体详情${detailRow ? ` · ${detailRow.name}` : ''}`}
        width={560}
        open={detailRow != null}
        onClose={() => setDetailRow(null)}
        destroyOnClose
      >
        {detailRow && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="Agent 类型">{detailRow.agent_type}</Descriptions.Item>
              <Descriptions.Item label="名称">{detailRow.name}</Descriptions.Item>
              <Descriptions.Item label="说明">{detailRow.description || '-'}</Descriptions.Item>
              <Descriptions.Item label="版本">{detailRow.version}</Descriptions.Item>
              <Descriptions.Item label="全局状态">
                <Tag color={detailRow.enabled ? 'green' : 'orange'}>
                  {detailRow.enabled ? '运行中' : '已停用'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="代码接入">
                <Tag color={detailRow.registered ? 'blue' : 'default'}>
                  {detailRow.registered ? '已接入' : '未接入'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="更新时间">
                {detailRow.updated_at ? dayjs(detailRow.updated_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
              </Descriptions.Item>
            </Descriptions>
            <Typography.Title level={5} style={{ margin: '8px 0 0' }}>
              输入 Schema
            </Typography.Title>
            <pre style={{ maxHeight: 320, overflow: 'auto', background: '#f6f7f9', padding: 12 }}>
              {detailRow.input_schema ? JSON.stringify(detailRow.input_schema, null, 2) : '（无）'}
            </pre>
          </Space>
        )}
      </Drawer>

      {/* 租户开通策略 */}
      <Drawer
        title="租户开通策略"
        width={680}
        open={policyOpen}
        onClose={() => setPolicyOpen(false)}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Typography.Text type="secondary">
            未配置视为开通；关闭后该租户不可用该智能体（以全局启用为前提）。
          </Typography.Text>
          <Select
            style={{ width: '100%' }}
            placeholder="选择租户"
            showSearch
            optionFilterProp="label"
            value={policyTenantId ?? undefined}
            onChange={(v) => onSelectTenant(v as number)}
            options={tenants.map((t) => ({ label: `${t.name}（#${t.id}）`, value: t.id }))}
          />
          {policyTenantId != null && (
            <>
              <Table<CapabilityItem>
                size="small"
                rowKey="agent_type"
                loading={capLoading}
                pagination={false}
                dataSource={capabilities}
                columns={[
                  { title: '智能体', dataIndex: 'name', key: 'name' },
                  { title: '类型', dataIndex: 'agent_type', key: 'agent_type' },
                  {
                    title: '全局',
                    dataIndex: 'global_enabled',
                    key: 'global_enabled',
                    render: (v: boolean) => (
                      <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag>
                    ),
                  },
                  {
                    title: '租户开通',
                    key: 'enabled',
                    render: (_: unknown, row: CapabilityItem) => (
                      <Switch
                        checked={row.enabled}
                        disabled={!canUpdate}
                        onChange={(checked) => toggleCapability(row.agent_type, checked)}
                      />
                    ),
                  },
                  {
                    title: '来源',
                    dataIndex: 'configured',
                    key: 'configured',
                    render: (v: boolean) => <Tag>{v ? '已配置' : '默认开通'}</Tag>,
                  },
                ]}
              />
              <Button
                type="primary"
                loading={capSaving}
                disabled={!canUpdate}
                onClick={() => void saveCapabilities()}
              >
                保存策略
              </Button>
            </>
          )}
        </Space>
      </Drawer>
    </Card>
  );
}
