import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  App as AntdApp,
  Button,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import {
  createModel,
  deleteModel,
  listModels,
  MODEL_TYPES,
  updateModel,
  type ModelItem,
  type ModelPayload,
} from '../services/models';

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

/**
 * 把一行记录转成请求体。
 * 刻意不带 api_key：后端返回的是脱敏值 "***"，原样回传会把真实 key 覆盖成 "***"。
 */
const toPayload = (row: ModelItem, overrides: Partial<ModelPayload> = {}): ModelPayload => ({
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
  ...overrides,
});

export default function ModelList() {
  const { message } = AntdApp.useApp();

  const [items, setItems] = useState<ModelItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modelType, setModelType] = useState<string | undefined>();
  const [togglingId, setTogglingId] = useState<number | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ModelItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listModels(modelType);
      setItems(res?.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [modelType]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (row: ModelItem) => {
    setEditing(row);
    // api_key 脱敏值不回填，留空表示沿用库里的原 key
    form.setFieldsValue({
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
    setModalOpen(true);
  };

  const onSubmit = async (values: FormValues) => {
    setSaving(true);
    try {
      const payload: ModelPayload = {
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
      };
      if (values.api_key) {
        payload.api_key = values.api_key;
      }
      if (editing) {
        await updateModel(editing.id, payload);
        message.success('模型已更新');
      } else {
        await createModel(payload);
        message.success('模型已新增');
      }
      setModalOpen(false);
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (row: ModelItem, enabled: boolean) => {
    setTogglingId(row.id);
    try {
      await updateModel(row.id, toPayload(row, { enabled }));
      message.success(enabled ? '已启用' : '已停用');
      await load();
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
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const columns: ColumnsType<ModelItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 70 },
    {
      title: '类型',
      dataIndex: 'model_type',
      key: 'model_type',
      width: 120,
      render: (v: string) => <Tag color={TYPE_COLOR[v] ?? 'default'}>{v}</Tag>,
    },
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: 'provider',
      dataIndex: 'provider',
      key: 'provider',
      width: 120,
      render: (v: string | null) => v ?? '-',
    },
    {
      title: 'base_url',
      dataIndex: 'base_url',
      key: 'base_url',
      ellipsis: true,
      render: (v: string | null) => v ?? '-',
    },
    {
      title: 'api_key',
      dataIndex: 'api_key',
      key: 'api_key',
      width: 100,
      render: (v: string | null) => v ?? '未配置',
    },
    {
      title: '参数',
      key: 'params',
      width: 150,
      render: (_: unknown, row: ModelItem) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          t={row.temperature ?? '-'} / {row.timeout_s ?? '-'}s / r={row.max_retries ?? '-'}
        </Typography.Text>
      ),
    },
    {
      title: '排序',
      dataIndex: 'sort_order',
      key: 'sort_order',
      width: 70,
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 80,
      render: (v: boolean, row: ModelItem) => (
        <Switch
          size="small"
          checked={v}
          loading={togglingId === row.id}
          onChange={(checked) => toggle(row, checked)}
        />
      ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (v: string | null) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      render: (_: unknown, row: ModelItem) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => openEdit(row)}>
            编辑
          </Button>
          <Popconfirm title="确认删除该模型？" onConfirm={() => onDelete(row)}>
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        模型注册表
        <Button type="primary" style={{ marginLeft: 16 }} onClick={openCreate}>
          新增模型
        </Button>
      </Typography.Title>

      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="按类型筛选"
          value={modelType}
          onChange={setModelType}
          allowClear
          style={{ width: 200 }}
          options={MODEL_TYPES}
        />
        <Button onClick={() => load()}>刷新</Button>
        <Typography.Text type="secondary">
          平台级资源，运行时按 model_type 取启用记录，模型改动即时影响调用
        </Typography.Text>
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

      <Table<ModelItem>
        rowKey="id"
        columns={columns}
        dataSource={items}
        loading={loading}
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: false, showTotal: (t) => `共 ${t} 条` }}
      />

      <Modal
        title={editing ? `编辑模型 #${editing.id}` : '新增模型'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={saving}
        width={680}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={onSubmit}
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
              <Form.Item name="api_key" label="api_key" extra={editing ? '留空表示保留原 key' : undefined}>
                <Input.Password placeholder={editing ? '不修改请留空' : '可留空'} />
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
    </div>
  );
}
