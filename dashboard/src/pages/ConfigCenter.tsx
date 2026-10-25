import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  App as AntdApp,
  Button,
  Col,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import {
  createRequest,
  createRollback,
  executeRequest,
  getRequestDetail,
  listRequests,
  OP_ADD,
  OP_DELETE,
  OP_MODIFY,
  OP_TYPE,
  REQUEST_STATUS,
  REVIEW_APPROVE,
  REVIEW_REJECT,
  reviewRequest,
  type ConfigRequestDetail,
  type ConfigRequestItem,
} from '../services/configCenter';

/** 状态着色：0 待审核 / 1 待执行 / 2 已驳回 / 3 已发布 */
const STATUS_COLOR: Record<number, string> = { 0: 'orange', 1: 'blue', 2: 'red', 3: 'green' };

const TIME_FMT = 'YYYY-MM-DD HH:mm:ss';

interface CreateValues {
  namespace: string;
  group_id: string;
  data_id: string;
  domain: string;
  op_type: number;
  title?: string;
  content_new?: string;
  content_format: string;
  reason?: string;
}

interface RollbackValues {
  namespace: string;
  group_id: string;
  data_id: string;
  domain: string;
  src_history_nid: number;
  title?: string;
  reason?: string;
}

export default function ConfigCenter() {
  const { message } = AntdApp.useApp();

  const [items, setItems] = useState<ConfigRequestItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [status, setStatus] = useState<number | undefined>();

  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createForm] = Form.useForm<CreateValues>();

  const [rollbackOpen, setRollbackOpen] = useState(false);
  const [rolling, setRolling] = useState(false);
  const [rollbackForm] = Form.useForm<RollbackValues>();

  const [detailId, setDetailId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ConfigRequestDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [comment, setComment] = useState('');
  const [acting, setActing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listRequests({ page, page_size: pageSize, status });
      setItems(res?.items ?? []);
      setTotal(res?.total ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const loadDetail = useCallback(
    async (id: number) => {
      setDetailLoading(true);
      try {
        const d = await getRequestDetail(id);
        setDetail(d);
      } catch (e) {
        message.error(e instanceof Error ? e.message : String(e));
        setDetail(null);
      } finally {
        setDetailLoading(false);
      }
    },
    [message],
  );

  const openDetail = (id: number) => {
    setDetailId(id);
    setDetail(null);
    setComment('');
    void loadDetail(id);
  };

  const onCreate = async (values: CreateValues) => {
    setCreating(true);
    try {
      const res = await createRequest(values);
      message.success(`申请已提交（#${res.id}），待复核`);
      setCreateOpen(false);
      createForm.resetFields();
      setPage(1);
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  };

  const onRollback = async (values: RollbackValues) => {
    setRolling(true);
    try {
      const res = await createRollback(values);
      message.success(`回滚申请已提交（#${res.id}），待复核`);
      setRollbackOpen(false);
      rollbackForm.resetFields();
      setPage(1);
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setRolling(false);
    }
  };

  const doReview = async (action: number) => {
    if (detailId === null) return;
    if (action === REVIEW_REJECT && !comment.trim()) {
      message.warning('驳回请填写意见');
      return;
    }
    setActing(true);
    try {
      await reviewRequest(detailId, action, comment.trim() || undefined);
      message.success(action === REVIEW_APPROVE ? '已通过复核，待执行' : '已驳回');
      await loadDetail(detailId);
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setActing(false);
    }
  };

  const doExecute = async () => {
    if (detailId === null) return;
    setActing(true);
    try {
      await executeRequest(detailId);
      message.success('已执行，配置已写入 Nacos');
      await loadDetail(detailId);
      await load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setActing(false);
    }
  };

  const columns: ColumnsType<ConfigRequestItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 70 },
    { title: 'dataId', dataIndex: 'data_id', key: 'data_id' },
    { title: 'group', dataIndex: 'group_id', key: 'group_id', width: 150 },
    { title: 'namespace', dataIndex: 'namespace', key: 'namespace', width: 150 },
    {
      title: '操作',
      dataIndex: 'op_type',
      key: 'op_type',
      width: 90,
      render: (v: number) => <Tag>{OP_TYPE[v] ?? v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: number) => <Tag color={STATUS_COLOR[v] ?? 'default'}>{REQUEST_STATUS[v] ?? v}</Tag>,
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (v: string | null) => v ?? '-',
    },
    { title: '申请人', dataIndex: 'applicant_user_id', key: 'applicant_user_id', width: 100 },
    {
      title: '申请时间',
      dataIndex: 'create_at',
      key: 'create_at',
      width: 170,
      render: (v: string | null) => (v ? dayjs(v).format(TIME_FMT) : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_: unknown, row: ConfigRequestItem) => (
        <Button type="link" size="small" onClick={() => openDetail(row.id)}>
          详情
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        配置中心
        <Button type="primary" style={{ marginLeft: 16 }} onClick={() => setCreateOpen(true)}>
          发起申请
        </Button>
        <Button style={{ marginLeft: 8 }} onClick={() => setRollbackOpen(true)}>
          发起回滚
        </Button>
      </Typography.Title>

      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="按状态筛选"
          value={status}
          onChange={(v) => {
            setStatus(v);
            setPage(1);
          }}
          allowClear
          style={{ width: 180 }}
          options={Object.entries(REQUEST_STATUS).map(([value, label]) => ({
            value: Number(value),
            label,
          }))}
        />
        <Button onClick={() => load()}>刷新</Button>
        <Typography.Text type="secondary">
          申请 → 复核 → 执行，只有「执行」会真正写 Nacos
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

      <Table<ConfigRequestItem>
        rowKey="id"
        columns={columns}
        dataSource={items}
        loading={loading}
        scroll={{ x: 'max-content' }}
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

      {/* 详情 + 复核 / 执行 */}
      <Drawer
        title={`配置申请 #${detailId ?? ''}`}
        open={detailId !== null}
        onClose={() => {
          setDetailId(null);
          setDetail(null);
        }}
        width={780}
      >
        <Spin spinning={detailLoading}>
          {detail && (
            <Space direction="vertical" style={{ width: '100%' }} size="middle">
              <div>
                <b>状态：</b>
                <Tag color={STATUS_COLOR[detail.status] ?? 'default'}>
                  {REQUEST_STATUS[detail.status] ?? detail.status}
                </Tag>
                <b style={{ marginLeft: 16 }}>操作：</b>
                <Tag>{OP_TYPE[detail.op_type] ?? detail.op_type}</Tag>
              </div>
              <div>
                <b>dataId：</b>
                <code>{detail.data_id}</code>
                <b style={{ marginLeft: 16 }}>group：</b>
                <code>{detail.group_id}</code>
                <b style={{ marginLeft: 16 }}>namespace：</b>
                <code>{detail.namespace}</code>
              </div>
              <div>
                <b>申请人：</b>
                {detail.applicant_user_id ?? '-'}
                <b style={{ marginLeft: 16 }}>复核人：</b>
                {detail.reviewer_user_id ?? '-'}
                <b style={{ marginLeft: 16 }}>提交时间：</b>
                {detail.create_at ? dayjs(detail.create_at).format(TIME_FMT) : '-'}
              </div>
              {detail.title ? (
                <div>
                  <b>标题：</b>
                  {detail.title}
                </div>
              ) : null}
              {detail.reason ? (
                <div>
                  <b>申请原因：</b>
                  {detail.reason}
                </div>
              ) : null}
              {detail.src_history_nid ? (
                <div>
                  <b>回滚来源：</b>
                  历史版本 nid={detail.src_history_nid}
                </div>
              ) : null}

              <Typography.Title level={5} style={{ marginBottom: 0 }}>
                内容对比
              </Typography.Title>
              <Row gutter={16}>
                <Col span={12}>
                  <Typography.Text type="secondary">当前内容（Nacos 实时）</Typography.Text>
                  <pre className="config-diff">{detail.old_content ?? '（无，可能是新增配置）'}</pre>
                </Col>
                <Col span={12}>
                  <Typography.Text type="secondary">申请内容</Typography.Text>
                  <pre className="config-diff">{detail.content_new ?? '（无，删除操作）'}</pre>
                </Col>
              </Row>

              {detail.status === 0 && (
                <>
                  <Input.TextArea
                    rows={2}
                    placeholder="复核意见（驳回必填）"
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                  />
                  <Space>
                    <Button
                      type="primary"
                      loading={acting}
                      onClick={() => doReview(REVIEW_APPROVE)}
                    >
                      通过复核
                    </Button>
                    <Button danger loading={acting} onClick={() => doReview(REVIEW_REJECT)}>
                      驳回
                    </Button>
                  </Space>
                </>
              )}

              {detail.status === 1 && (
                <>
                  <Alert type="info" showIcon message="复核已通过，执行后将直接写入 Nacos" />
                  <Popconfirm title="确认执行并写入 Nacos？" onConfirm={doExecute}>
                    <Button type="primary" loading={acting}>
                      执行写入 Nacos
                    </Button>
                  </Popconfirm>
                </>
              )}

              {detail.status === 2 && <Alert type="warning" showIcon message="已驳回，不可再执行" />}
              {detail.status === 3 && <Alert type="success" showIcon message="已发布：配置已写入 Nacos" />}
            </Space>
          )}
        </Spin>
      </Drawer>

      {/* 发起申请 */}
      <Modal
        title="发起配置变更申请"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        confirmLoading={creating}
        width={640}
        destroyOnClose
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={onCreate}
          initialValues={{ domain: 'prompt', op_type: OP_MODIFY, content_format: 'json' }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="namespace" label="namespace" rules={[{ required: true }]}>
                <Input placeholder="如 dev" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="group_id" label="group" rules={[{ required: true }]}>
                <Input placeholder="如 DEFAULT_GROUP" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="data_id"
            label="dataId"
            rules={[{ required: true }]}
            extra="后缀为 .json / .yaml 时后端会校验内容格式"
          >
            <Input placeholder="如 prompt.qa.system.json" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="domain" label="业务域" rules={[{ required: true }]}>
                <Select
                  options={[
                    { value: 'prompt', label: 'prompt' },
                    { value: 'agent', label: 'agent' },
                    { value: 'tool', label: 'tool' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="op_type" label="操作类型" rules={[{ required: true }]}>
                <Select
                  options={[
                    { value: OP_ADD, label: '新增' },
                    { value: OP_MODIFY, label: '修改' },
                    { value: OP_DELETE, label: '删除' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="content_format" label="内容格式" rules={[{ required: true }]}>
                <Select
                  options={[
                    { value: 'json', label: 'json' },
                    { value: 'yaml', label: 'yaml' },
                    { value: 'text', label: 'text' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="title" label="标题">
            <Input placeholder="一句话说明这次变更" />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.op_type !== cur.op_type}>
            {({ getFieldValue }) => {
              const isDelete = getFieldValue('op_type') === OP_DELETE;
              return (
                <Form.Item
                  name="content_new"
                  label={isDelete ? '配置内容（删除无需填写，忽略）' : '配置内容'}
                  rules={isDelete ? [] : [{ required: true, message: '新增/修改必须填写内容' }]}
                >
                  <Input.TextArea rows={8} disabled={isDelete} placeholder="粘贴完整配置内容" />
                </Form.Item>
              );
            }}
          </Form.Item>
          <Form.Item name="reason" label="变更原因">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 发起回滚 */}
      <Modal
        title="发起配置回滚"
        open={rollbackOpen}
        onCancel={() => setRollbackOpen(false)}
        onOk={() => rollbackForm.submit()}
        confirmLoading={rolling}
        width={560}
        destroyOnClose
      >
        <Form
          form={rollbackForm}
          layout="vertical"
          onFinish={onRollback}
          initialValues={{ domain: 'prompt' }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="namespace" label="namespace" rules={[{ required: true }]}>
                <Input placeholder="如 dev" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="group_id" label="group" rules={[{ required: true }]}>
                <Input placeholder="如 DEFAULT_GROUP" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="data_id" label="dataId" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="domain" label="业务域" rules={[{ required: true }]}>
                <Select
                  options={[
                    { value: 'prompt', label: 'prompt' },
                    { value: 'agent', label: 'agent' },
                    { value: 'tool', label: 'tool' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="src_history_nid"
                label="历史版本 nid"
                rules={[{ required: true, message: '请填写要回滚到哪个历史版本' }]}
                extra="Nacos 控制台的配置历史里可以看到 nid"
              >
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="title" label="标题">
            <Input placeholder="留空则自动生成「回滚至历史 nid=x」" />
          </Form.Item>
          <Form.Item name="reason" label="回滚原因">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
