import { useCallback, useEffect, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Card,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Progress,
  Result,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ProTable, type ProColumns } from '../../../components/ProTable';

import {
  getQaQuality,
  getQaResult,
  listQaResults,
  submitQaReview,
  type QaResultDetail as ApiQaResultDetail,
  type QaResultItem,
  type RagasEval,
} from '../../../services/qaResults';
import { hasScope } from '../../../services/auth';

type QaStatus = 'success' | 'failed' | 'partial';
type EvalStatus = 'success' | 'failed' | 'pending' | 'running';

interface QaResultRow {
  id: string;
  traceId: string;
  tenantId: number;
  userId: number;
  sessionId: string;
  question: string;
  answer: string;
  answerMode: string;
  queryType: string;
  confidence: number;
  status: QaStatus;
  latencyMs: number;
  createdAt: string;
  errorMsg?: string;
  retrievedContexts: { docId: string; content: string; score: number }[];
  sources: string[];
  referenceAnswer?: string | null;
  tokenUsage: Record<string, unknown> | null;
  extra: Record<string, unknown> | null;
}

interface RagasEvalRow {
  id: string;
  qaResultId: string;
  traceId: string;
  tenantId: number;
  evaluator: string;
  evaluatorModel: string;
  datasetVersion: string;
  faithfulness: number;
  answerRelevancy: number;
  contextPrecision: number;
  contextRecall: number;
  answerCorrectness: number | null;
  metrics: Record<string, unknown>;
  status: EvalStatus;
  errorMsg?: string | null;
  evalAt: string;
  createdAt: string;
  updatedAt: string;
}

const METRIC_FIELDS: {
  key: keyof Pick<
    RagasEvalRow,
    'faithfulness' | 'answerRelevancy' | 'contextPrecision' | 'contextRecall' | 'answerCorrectness'
  >;
  label: string;
}[] = [
  { key: 'faithfulness', label: '忠实度 faithfulness' },
  { key: 'answerRelevancy', label: '答案相关性 answer_relevancy' },
  { key: 'contextPrecision', label: '上下文精确率 context_precision' },
  { key: 'contextRecall', label: '上下文召回率 context_recall' },
  { key: 'answerCorrectness', label: '答案正确性 answer_correctness' },
];

const STATUS_COLOR: Record<string, string> = {
  success: 'success',
  failed: 'error',
  partial: 'warning',
  pending: 'processing',
  running: 'processing',
};
const STATUS_LABEL: Record<string, string> = {
  success: '成功',
  failed: '失败',
  partial: '部分成功',
  pending: '待评估',
  running: '评估中',
};
const ANSWER_MODE_COLOR: Record<string, string> = {
  rag: 'blue',
  llm_direct: 'green',
  general: 'orange',
  fallback: 'red',
};

const toTime = (value: string | null | undefined): string =>
  value ? value.replace('T', ' ').slice(0, 19) : '-';

const mapItem = (row: QaResultItem): QaResultRow => ({
  id: row.id,
  traceId: row.trace_id ?? '',
  tenantId: row.tenant_id,
  userId: row.user_id,
  sessionId: row.session_id,
  question: row.question,
  answer: '',
  answerMode: row.answer_mode ?? '-',
  queryType: row.query_type ?? '-',
  confidence: row.confidence ?? 0,
  status: (row.status as QaStatus) ?? 'success',
  latencyMs: row.latency_ms ?? 0,
  createdAt: toTime(row.created_at),
  retrievedContexts: [],
  sources: [],
  tokenUsage: null,
  extra: null,
});

const mapDetail = (row: ApiQaResultDetail): QaResultRow => ({
  ...mapItem(row),
  traceId: row.trace_id ?? '',
  answer: row.answer ?? '',
  retrievedContexts: (row.retrieved_contexts ?? []).map((c) => ({
    docId: c.doc_id,
    content: c.content,
    score: Number(c.score ?? 0),
  })),
  sources: row.sources ?? [],
  referenceAnswer: row.reference_answer,
  tokenUsage: row.token_usage ?? null,
  extra: row.extra ?? null,
  errorMsg: row.error_msg ?? undefined,
  createdAt: toTime(row.created_at),
});

const mapEval = (row: RagasEval): RagasEvalRow => ({
  id: row.id,
  qaResultId: row.qa_result_id,
  traceId: row.trace_id ?? '',
  tenantId: row.tenant_id,
  evaluator: row.evaluator,
  evaluatorModel: row.evaluator_model ?? '-',
  datasetVersion: row.dataset_version ?? '-',
  faithfulness: row.faithfulness ?? 0,
  answerRelevancy: row.answer_relevancy ?? 0,
  contextPrecision: row.context_precision ?? 0,
  contextRecall: row.context_recall ?? 0,
  answerCorrectness: row.answer_correctness,
  metrics: row.metrics ?? {},
  status: (row.status as EvalStatus) ?? 'pending',
  errorMsg: row.error_msg,
  evalAt: toTime(row.eval_at),
  createdAt: toTime(row.created_at),
  updatedAt: toTime(row.updated_at),
});

/** 多行文本：保留换行、长词折行，浅底卡片，避免撑破排版。 */
function LongText({ value }: { value?: string | null }) {
  const text = (value ?? '').trim();
  return (
    <div
      style={{
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        lineHeight: 1.7,
        background: '#fafafa',
        border: '1px solid #f0f0f0',
        borderRadius: 6,
        padding: '8px 12px',
      }}
    >
      {text || <Typography.Text type="secondary">-</Typography.Text>}
    </div>
  );
}

/** 检索上下文：每条一个浅底卡片，docId + score + 正文。 */
function ContextList({ contexts }: { contexts: QaResultRow['retrievedContexts'] }) {
  if (contexts.length === 0) {
    return <Typography.Text type="secondary">-</Typography.Text>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {contexts.map((c) => (
        <div
          key={c.docId}
          style={{
            border: '1px solid #f0f0f0',
            borderRadius: 6,
            background: '#fafafa',
            padding: '8px 12px',
          }}
        >
          <Space size={8} style={{ marginBottom: 4 }}>
            <Tag>{c.docId}</Tag>
            <Typography.Text type="secondary">score {c.score.toFixed(2)}</Typography.Text>
          </Space>
          <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.7 }}>
            {c.content}
          </div>
        </div>
      ))}
    </div>
  );
}

/** 问答字段统一展示（详情 / 质量分析 / 问答测评复用）。 */
function JsonBlock({ value }: { value: Record<string, unknown> | null }) {
  if (!value || Object.keys(value).length === 0) {
    return <Typography.Text type="secondary">-</Typography.Text>;
  }
  return (
    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function QaInfo({ row }: { row: QaResultRow }) {
  return (
    <Descriptions
      column={1}
      bordered
      size="small"
      styles={{
        label: { width: 140, verticalAlign: 'top' },
        content: { wordBreak: 'break-word' },
      }}
    >
      <Descriptions.Item label="traceId">{row.traceId || '-'}</Descriptions.Item>
      <Descriptions.Item label="租户 / 用户">
        {row.tenantId} / {row.userId}
      </Descriptions.Item>
      <Descriptions.Item label="会话ID">{row.sessionId}</Descriptions.Item>
      <Descriptions.Item label="问题">
        <LongText value={row.question} />
      </Descriptions.Item>
      <Descriptions.Item label="回答">
        <LongText value={row.answer} />
      </Descriptions.Item>
      <Descriptions.Item label="回答模式 / 查询类型">
        <Space size={8}>
          <Tag color={ANSWER_MODE_COLOR[row.answerMode] ?? 'default'}>{row.answerMode}</Tag>
          <span>{row.queryType}</span>
        </Space>
      </Descriptions.Item>
      <Descriptions.Item label="置信度">
        <Progress percent={Math.round(row.confidence * 100)} size="small" />
      </Descriptions.Item>
      <Descriptions.Item label="状态">
        <Tag color={STATUS_COLOR[row.status] ?? 'default'}>
          {STATUS_LABEL[row.status] ?? row.status}
        </Tag>
      </Descriptions.Item>
      <Descriptions.Item label="耗时">{row.latencyMs} ms</Descriptions.Item>
      <Descriptions.Item label="Token 用量">
        <JsonBlock value={row.tokenUsage} />
      </Descriptions.Item>
      <Descriptions.Item label="扩展信息">
        <JsonBlock value={row.extra} />
      </Descriptions.Item>
      <Descriptions.Item label="时间">{row.createdAt}</Descriptions.Item>
      {row.errorMsg ? (
        <Descriptions.Item label="错误">
          <LongText value={row.errorMsg} />
        </Descriptions.Item>
      ) : null}
      <Descriptions.Item label="检索上下文">
        <ContextList contexts={row.retrievedContexts} />
      </Descriptions.Item>
      <Descriptions.Item label="来源">
        {row.sources.length > 0 ? (
          <Space wrap size={4}>
            {row.sources.map((s) => (
              <Tag key={s}>{s}</Tag>
            ))}
          </Space>
        ) : (
          <Typography.Text type="secondary">-</Typography.Text>
        )}
      </Descriptions.Item>
      <Descriptions.Item label="人工标准答案">
        <LongText value={row.referenceAnswer} />
      </Descriptions.Item>
    </Descriptions>
  );
}

/** 问答结果：对接 /api/v1/tenant/qa/results（列表/详情/测评/质量分析）。 */
export default function QaResults() {
  const { message, modal } = AntdApp.useApp();
  const canPage = hasScope('qa_result:page');
  const canView = hasScope('qa_result:view');
  const canReview = hasScope('qa_result:review');

  const [rows, setRows] = useState<QaResultRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [loading, setLoading] = useState(false);

  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<QaResultRow | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [qualityOpen, setQualityOpen] = useState(false);
  const [qualityRow, setQualityRow] = useState<QaResultRow | null>(null);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [evals, setEvals] = useState<RagasEvalRow[]>([]);
  const [evalsLoading, setEvalsLoading] = useState(false);
  const [evalDetail, setEvalDetail] = useState<RagasEvalRow | null>(null);

  const [evalOpen, setEvalOpen] = useState(false);
  const [evalRow, setEvalRow] = useState<QaResultRow | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const [evalForm] = Form.useForm();

  // Form 在 evalRow 就绪后才挂载，这里补一次回填，确保人工标准答案预填
  useEffect(() => {
    if (evalOpen && evalRow) {
      evalForm.setFieldsValue({ referenceAnswer: evalRow.referenceAnswer ?? '' });
    }
  }, [evalOpen, evalRow, evalForm]);

  const load = useCallback(async () => {
    if (!canPage) return;
    setLoading(true);
    try {
      const res = await listQaResults({ page, page_size: pageSize });
      setRows(res.items.map(mapItem));
      setTotal(res.total);
    } catch (e) {
      message.error(e instanceof Error ? e.message : '问答结果加载失败');
    } finally {
      setLoading(false);
    }
  }, [canPage, message, page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (row: QaResultRow) => {
    setDetailOpen(true);
    setDetail(null);
    setDetailLoading(true);
    try {
      const res = await getQaResult(row.id);
      setDetail(mapDetail(res));
    } catch (e) {
      message.error(e instanceof Error ? e.message : '详情加载失败');
    } finally {
      setDetailLoading(false);
    }
  };

  const loadEvals = useCallback(
    async (id: string) => {
      setEvalsLoading(true);
      try {
        const res = await getQaQuality(id);
        setEvals(res.items.map(mapEval));
      } catch (e) {
        message.error(e instanceof Error ? e.message : 'RAGAS 评估加载失败');
      } finally {
        setEvalsLoading(false);
      }
    },
    [message],
  );

  const openQuality = async (row: QaResultRow) => {
    setQualityOpen(true);
    setQualityRow(null);
    setEvals([]);
    setEvalDetail(null);
    setQualityLoading(true);
    try {
      const [detailRes] = await Promise.all([getQaResult(row.id), loadEvals(row.id)]);
      setQualityRow(mapDetail(detailRes));
    } catch (e) {
      message.error(e instanceof Error ? e.message : '质量分析加载失败');
    } finally {
      setQualityLoading(false);
    }
  };

  const openEval = async (row: QaResultRow) => {
    setEvalOpen(true);
    setEvalRow(null);
    evalForm.resetFields();
    setEvalLoading(true);
    try {
      const res = await getQaResult(row.id);
      const mapped = mapDetail(res);
      setEvalRow(mapped);
      evalForm.setFieldsValue({ referenceAnswer: mapped.referenceAnswer ?? '' });
    } catch (e) {
      message.error(e instanceof Error ? e.message : '问答详情加载失败');
    } finally {
      setEvalLoading(false);
    }
  };

  const startEvaluation = async () => {
    if (!evalRow) return;
    try {
      await evalForm.validateFields();
    } catch {
      return;
    }
    const referenceAnswer = String(evalForm.getFieldValue('referenceAnswer') ?? '').trim();
    modal.confirm({
      title: '确认开始测评？',
      content: '将使用人工标准答案对该问答结果进行 RAGAS 测评。',
      okText: '开始测评',
      cancelText: '取消',
      onOk: async () => {
        try {
          await submitQaReview(evalRow.id, referenceAnswer);
          message.success('测评任务已提交');
          setEvalOpen(false);
          setEvalRow(null);
          if (qualityOpen && qualityRow?.id === evalRow.id) {
            void loadEvals(evalRow.id);
          }
          void load();
        } catch (e) {
          message.error(e instanceof Error ? e.message : '测评提交失败');
        }
      },
    });
  };

  const columns: ProColumns<QaResultRow>[] = [
    { title: '会话ID', dataIndex: 'sessionId', width: 140, ellipsis: true },
    { title: '租户', dataIndex: 'tenantId', width: 80 },
    { title: '用户', dataIndex: 'userId', width: 80 },
    { title: '问题', dataIndex: 'question', ellipsis: true },
    {
      title: '回答模式',
      dataIndex: 'answerMode',
      width: 110,
      render: (_, row) => (
        <Tag color={ANSWER_MODE_COLOR[row.answerMode] ?? 'default'}>{row.answerMode}</Tag>
      ),
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      width: 130,
      render: (_, row) => <Progress percent={Math.round(row.confidence * 100)} size="small" />,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (_, row) => (
        <Tag color={STATUS_COLOR[row.status] ?? 'default'}>
          {STATUS_LABEL[row.status] ?? row.status}
        </Tag>
      ),
    },
    {
      title: '耗时',
      dataIndex: 'latencyMs',
      width: 90,
      render: (_, row) => `${row.latencyMs} ms`,
    },
    { title: '时间', dataIndex: 'createdAt', width: 170 },
    {
      title: '操作',
      width: 220,
      valueType: 'option',
      render: (_, row) => (
        <Space size={12}>
          {canView && (
            <Typography.Link onClick={() => void openDetail(row)}>详情</Typography.Link>
          )}
          {canReview && (
            <Typography.Link onClick={() => void openQuality(row)}>质量分析</Typography.Link>
          )}
          {canReview && (
            <Typography.Link onClick={() => void openEval(row)}>问答测评</Typography.Link>
          )}
        </Space>
      ),
    },
  ];

  const evalColumns: ColumnsType<RagasEvalRow> = [
    { title: '评估时间', dataIndex: 'evalAt', width: 170 },
    { title: '评估器', dataIndex: 'evaluator', width: 90 },
    { title: '评估模型', dataIndex: 'evaluatorModel', width: 180, ellipsis: true },
    { title: '数据集', dataIndex: 'datasetVersion', width: 90 },
    { title: 'traceId', dataIndex: 'traceId', width: 190, ellipsis: true },
    { title: '租户', dataIndex: 'tenantId', width: 80 },
    {
      title: '忠实度',
      dataIndex: 'faithfulness',
      width: 90,
      render: (v: number) => v?.toFixed(2) ?? '-',
    },
    {
      title: '答案相关性',
      dataIndex: 'answerRelevancy',
      width: 100,
      render: (v: number) => v?.toFixed(2) ?? '-',
    },
    {
      title: '上下文精确率',
      dataIndex: 'contextPrecision',
      width: 120,
      render: (v: number) => v?.toFixed(2) ?? '-',
    },
    {
      title: '上下文召回率',
      dataIndex: 'contextRecall',
      width: 120,
      render: (v: number) => v?.toFixed(2) ?? '-',
    },
    {
      title: '答案正确性',
      dataIndex: 'answerCorrectness',
      width: 100,
      render: (v: number) => (v == null ? '-' : v.toFixed(2)),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_, row) => (
        <Tag color={STATUS_COLOR[row.status] ?? 'default'}>
          {STATUS_LABEL[row.status] ?? row.status}
        </Tag>
      ),
    },
    {
      title: '操作',
      width: 80,
      render: (_, row) => <Typography.Link onClick={() => setEvalDetail(row)}>详情</Typography.Link>,
    },
  ];

  if (!canPage) {
    return <Result status="403" title="无权限" subTitle="你没有查看问答结果的权限" />;
  }

  return (
    <Card title={<Typography.Title level={4} style={{ margin: 0 }}>问答结果</Typography.Title>}>
      <ProTable<QaResultRow>
        rowKey="id"
        search={false}
        options={false}
        columns={columns}
        dataSource={rows}
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize ?? pageSize);
          },
        }}
        scroll={{ x: 'max-content' }}
      />

      {/* 问答详情 */}
      <Drawer
        title="问答详情"
        width={820}
        open={detailOpen}
        onClose={() => {
          setDetailOpen(false);
          setDetail(null);
        }}
      >
        <Spin spinning={detailLoading}>
          {detail ? <QaInfo row={detail} /> : <Empty description="暂无数据" />}
        </Spin>
      </Drawer>

      {/* 质量分析：RAGAS 评估列表 */}
      <Drawer
        title="RAGAS 质量分析"
        width={1080}
        open={qualityOpen}
        onClose={() => {
          setQualityOpen(false);
          setQualityRow(null);
          setEvals([]);
          setEvalDetail(null);
        }}
      >
        <Spin spinning={qualityLoading}>
          {qualityRow ? (
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <QaInfo row={qualityRow} />
              <Table<RagasEvalRow>
                rowKey="id"
                size="small"
                loading={evalsLoading}
                columns={evalColumns}
                dataSource={evals}
                pagination={false}
                scroll={{ x: 'max-content' }}
                locale={{ emptyText: <Empty description="暂无 RAGAS 评估结果" /> }}
              />
            </Space>
          ) : (
            <Empty description="暂无数据" />
          )}
        </Spin>
      </Drawer>

      {/* RAGAS 指标详情 */}
      <Modal
        title="RAGAS 指标详情"
        open={evalDetail !== null}
        onCancel={() => setEvalDetail(null)}
        footer={null}
        width={760}
      >
        {evalDetail ? (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Descriptions
              column={1}
              size="small"
              bordered
              styles={{
                label: { width: 130, verticalAlign: 'top' },
                content: { wordBreak: 'break-word' },
              }}
            >
              <Descriptions.Item label="记录ID">{evalDetail.id}</Descriptions.Item>
              <Descriptions.Item label="问答结果ID">{evalDetail.qaResultId}</Descriptions.Item>
              <Descriptions.Item label="traceId">{evalDetail.traceId || '-'}</Descriptions.Item>
              <Descriptions.Item label="租户">{evalDetail.tenantId}</Descriptions.Item>
              <Descriptions.Item label="评估器">{evalDetail.evaluator}</Descriptions.Item>
              <Descriptions.Item label="评估模型">{evalDetail.evaluatorModel}</Descriptions.Item>
              <Descriptions.Item label="数据集版本">{evalDetail.datasetVersion}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_COLOR[evalDetail.status] ?? 'default'}>
                  {STATUS_LABEL[evalDetail.status] ?? evalDetail.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="评估时间">{evalDetail.evalAt}</Descriptions.Item>
              <Descriptions.Item label="创建时间">{evalDetail.createdAt}</Descriptions.Item>
              <Descriptions.Item label="更新时间">{evalDetail.updatedAt}</Descriptions.Item>
              {evalDetail.errorMsg ? (
                <Descriptions.Item label="错误信息">
                  <LongText value={evalDetail.errorMsg} />
                </Descriptions.Item>
              ) : null}
            </Descriptions>
            {METRIC_FIELDS.map((m) => {
              const value = evalDetail[m.key];
              return (
                <div key={m.key}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>{m.label}</span>
                    <span>{value == null ? '-' : value.toFixed(3)}</span>
                  </div>
                  <Progress
                    percent={value == null ? 0 : Math.round(value * 100)}
                    size="small"
                    showInfo={false}
                  />
                </div>
              );
            })}

            <Divider style={{ margin: '4px 0' }}>原始指标</Divider>
            <LongText value={JSON.stringify(evalDetail.metrics, null, 2)} />
          </Space>
        ) : null}
      </Modal>

      {/* 问答测评：展示字段 + 填写人工标准答案 */}
      <Drawer
        title="问答测评"
        width={820}
        open={evalOpen}
        onClose={() => {
          setEvalOpen(false);
          setEvalRow(null);
        }}
      >
        <Spin spinning={evalLoading}>
          {evalRow ? (
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <QaInfo row={evalRow} />

              <Form form={evalForm} layout="vertical">
                <Form.Item
                  name="referenceAnswer"
                  label="人工标准答案"
                  rules={[{ required: true, whitespace: true, message: '请填写人工标准答案' }]}
                >
                  <Input.TextArea
                    rows={5}
                    placeholder="请输入该问题的人工标准答案（用于 RAGAS 测评）"
                  />
                </Form.Item>
              </Form>

              <Space>
                <Button onClick={() => setEvalOpen(false)}>取消</Button>
                <Button type="primary" onClick={() => void startEvaluation()}>
                  开始测评
                </Button>
              </Space>
            </Space>
          ) : (
            <Empty description="暂无数据" />
          )}
        </Spin>
      </Drawer>
    </Card>
  );
}
