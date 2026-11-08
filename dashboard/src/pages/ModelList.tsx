import { useCallback, useRef, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Col,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  Result,
} from 'antd';
import { ProTable, type ProColumns, type ActionType } from '../components/ProTable';
import dayjs from 'dayjs';

import {
  createModel,
  deleteModel,
  getModel,
  listModels,
  MODEL_TYPES,
  setModelStatus,
  updateModel,
  type ModelItem,
  type ModelPayload,
} from '../services/models';
import { sortByTimeThenId } from '../utils/sort';
import { hasScope } from '../services/auth';

const TYPE_COLOR: Record<string, string> = {
  llm: 'blue',
  embedding: 'green',
  reranker: 'purple',
  classifier: 'orange',
};

interface FormValues {
  model_type: string;
  name: string;
  provider?: string;
  base_url?: string;
  api_key?: string;
  endpoint_path?: string;
  temperature?: number;
  timeout_s?: number;
  max_retries?: number;
  enabled: boolean;
  sort_order: number;
  description?: string;
}



export default function ModelList() {
  const { message, modal } = AntdApp.useApp();
  const actionRef = useRef<ActionType>();
  const modelTypeEnum = Object.fromEntries(MODEL_TYPES.map((o) => [o.value, o.label]));

  // 模型配置权限点（与后端 Scope 对齐）：列表按 page 拦，写操作按各自 scope 拦
  const canPage = hasScope('model:page');
  const canAdd = hasScope('model:add');
  const canUpdate = hasScope('model:update');
  const canDelete = hasScope('model:delete');
  const canView = hasScope('model:view');
  const canStatus = hasScope('model:status');

  const [togglingId, setTogglingId] = useState<number | null>(null);
  const [drawerModel, setDrawerModel] = useState<ModelItem | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<ModelItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [createForm] = Form.useForm<FormValues>();
  const [editForm] = Form.useForm<FormValues>();

  const request = useCallback(async (params: any) => {
    const res = await listModels({ model_type: params.model_type, page: params.current ?? 1, page_size: params.pageSize ?? 20 });
    return { data: sortByTimeThenId(res?.items ?? []), success: true, total: res?.total ?? 0 };
  }, []);

  const openCreate = () => {
    createForm.resetFields();
    setCreateOpen(true);
  };

  const openEdit = (row: ModelItem) => {
    setEditTarget(row);
    // api_key 脱敏值不回填，留空表示沿用库里的原 key
    editForm.resetFields();
    editForm.setFieldsValue({
      model_type: row.model_type,
      name: row.name,
      provider: row.provider ?? undefined,
      base_url: row.base_url ?? undefined,
      endpoint_path: row.endpoint_path ?? undefined,
      temperature: row.temperature ?? undefined,
      timeout_s: row.timeout_s ?? undefined,
      max_retries: row.max_retries ?? undefined,
      enabled: row.enabled,
      sort_order: row.sort_order,
      description: row.description ?? undefined,
      api_key: undefined,
    });
    setEditOpen(true);
  };

  const buildPayload = (values: FormValues): ModelPayload => ({
    model_type: values.model_type,
    name: values.name,
    provider: values.provider || undefined,
    base_url: values.base_url || undefined,
    endpoint_path: values.endpoint_path || undefined,
    temperature: values.temperature ?? undefined,
    timeout_s: values.timeout_s ?? undefined,
    max_retries: values.max_retries ?? undefined,
    enabled: values.enabled,
    sort_order: values.sort_order,
    description: values.description || undefined,
  });

  const onCreate = async (values: FormValues) => {
    setSaving(true);
    try {
      const payload = buildPayload(values);
      if (values.api_key) payload.api_key = values.api_key;
      await createModel(payload);
      message.success('模型已新增');
      setCreateOpen(false);
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const onEdit = async (values: FormValues) => {
    if (!editTarget) return;
    setSaving(true);
    try {
      const payload = buildPayload(values);
      // api_key 留空表示沿用原 key
      if (values.api_key) payload.api_key = values.api_key;
      await updateModel(editTarget.id, payload);
      message.success('模型已更新');
      setEditOpen(false);
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (row: ModelItem, enabled: boolean) => {
    setTogglingId(row.id);
    try {
      await setModelStatus(row.id, enabled);
      message.success(enabled ? '已启用' : '已停用');
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setTogglingId(null);
    }
  };

  const onDelete = async (row: ModelItem) => {
    try {
      await deleteModel(row.id);
      message.success('模型已删除');
      await actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const openDetail = async (id: number) => {
    setDrawerModel(null);
    try {
      const m = await getModel(id);
      setDrawerModel(m);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const columns: ProColumns<ModelItem>[] = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 70, search: false },
    {
      title: '类型',
      dataIndex: 'model_type',
      key: 'model_type',
      width: 120,
      valueType: 'select',
      valueEnum: modelTypeEnum,
      render: (value: any) => <Tag color={TYPE_COLOR[value] ?? 'default'}>{value}</Tag>,
    },
    { title: '名称', dataIndex: 'name', key: 'name', search: false },
    {
      title: '排序',
      dataIndex: 'sort_order',
      key: 'sort_order',
      width: 70,
      search: false,
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 80,
      search: false,
      render: (value: any, row: ModelItem) => (
        <Switch
        size="small"
        checked={value}
        disabled={!canStatus}
        loading={togglingId === row.id}
        onChange={(checked) =>
            modal.confirm({
              title: '确认切换启用状态？',
              content: checked ? '启用后该模型可立即被调用' : '停用后该模型不可被调用，影响线上',
              okText: '确定',
              cancelText: '取消',
              onOk: () => toggle(row, checked),
            })
          }
        />
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
      render: (_: unknown, row: ModelItem) => (
        <Space size={4}>
          {canView && (
            <Button type="link" size="small" onClick={() => openDetail(row.id)}>
              详情
            </Button>
          )}
          {canUpdate && (
            <Button type="link" size="small" onClick={() => openEdit(row)}>
              编辑
            </Button>
          )}
          {canDelete && (
            <Popconfirm title="确认删除该模型？" onConfirm={() => onDelete(row)}>
              <Button type="link" size="small" danger>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  if (!canPage) {
    return <Result status="403" title="无权限" subTitle="你没有查看模型配置的权限" />;
  }

  return (
    <div>
      <ProTable<ModelItem>
        headerTitle="模型注册表"
        actionRef={actionRef}
        toolBarRender={() =>
          canAdd
            ? [
                <Button key="add" type="primary" onClick={openCreate}>
                  新增模型
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

      {/* 新增模型：类型可选，api_key 可留空 */}
      <Modal
        title="新增模型"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        confirmLoading={saving}
        okText="创建"
        width={680}
        destroyOnClose
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={onCreate}
          initialValues={{ enabled: true, sort_order: 0, model_type: 'llm' }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="model_type" label="类型" rules={[{ required: true }]}>
                <Select options={MODEL_TYPES} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                <Input placeholder="如 qwen-max" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="provider" label="provider">
                <Input placeholder="如 openai / dashscope" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="api_key" label="api_key">
                <Input.Password placeholder="可留空" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="base_url" label="base_url">
            <Input placeholder="如 https://dashscope.aliyuncs.com/compatible-mode/v1" />
          </Form.Item>
          <Form.Item name="endpoint_path" label="endpoint_path">
            <Input placeholder="如 /embeddings，按需填写" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item name="temperature" label="temperature">
                <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="timeout_s" label="超时（秒）">
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="max_retries" label="重试次数">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="sort_order" label="排序" rules={[{ required: true }]}>
                <InputNumber style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑模型：类型不可改，api_key 留空保留原值 */}
      <Modal
        title={`编辑模型 #${editTarget?.id ?? ''}`}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={() => editForm.submit()}
        confirmLoading={saving}
        okText="保存"
        width={680}
        destroyOnClose
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={onEdit}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="model_type" label="类型" rules={[{ required: true }]} extra="类型创建后不可修改">
                <Select options={MODEL_TYPES} disabled />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                <Input placeholder="如 qwen-max" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="provider" label="provider">
                <Input placeholder="如 openai / dashscope" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="api_key" label="api_key" extra="留空表示保留原 key">
                <Input.Password placeholder="不修改请留空" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="base_url" label="base_url">
            <Input placeholder="如 https://dashscope.aliyuncs.com/compatible-mode/v1" />
          </Form.Item>
          <Form.Item name="endpoint_path" label="endpoint_path">
            <Input placeholder="如 /embeddings，按需填写" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item name="temperature" label="temperature">
                <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="timeout_s" label="超时（秒）">
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="max_retries" label="重试次数">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="sort_order" label="排序" rules={[{ required: true }]}>
                <InputNumber style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
      <Drawer
        title={`模型详情 #${drawerModel?.id ?? ''}`}
        open={drawerModel !== null}
        onClose={() => setDrawerModel(null)}
        width={520}
      >
        {drawerModel && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="ID">{drawerModel.id}</Descriptions.Item>
            <Descriptions.Item label="类型">{drawerModel.model_type}</Descriptions.Item>
            <Descriptions.Item label="名称">{drawerModel.name}</Descriptions.Item>
            <Descriptions.Item label="provider">{drawerModel.provider ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="base_url">{drawerModel.base_url ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="api_key">{drawerModel.api_key ?? '未配置'}</Descriptions.Item>
            <Descriptions.Item label="endpoint_path">{drawerModel.endpoint_path ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="temperature">{drawerModel.temperature ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="超时(秒)">{drawerModel.timeout_s ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="重试次数">{drawerModel.max_retries ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="启用">{drawerModel.enabled ? '是' : '否'}</Descriptions.Item>
            <Descriptions.Item label="排序">{drawerModel.sort_order}</Descriptions.Item>
            <Descriptions.Item label="说明">{drawerModel.description ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="更新时间">
              {drawerModel.updated_at ? dayjs(drawerModel.updated_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
}
