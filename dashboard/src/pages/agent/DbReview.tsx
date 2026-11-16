import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import dayjs from 'dayjs';

import { listDbConnections, type DbConnectionItem } from '../../services/dbConnections';
import {
  approveChange,
  getChange,
  listChanges,
  submitChange,
  type ChangeItem,
  uploadReviewFile,
  type ReviewResult,
} from '../../services/dbChange';

const RISK_COLOR: Record<string, string> = {
  low: 'green',
  medium: 'gold',
  high: 'orange',
  critical: 'red',
};

const STATUS_COLOR: Record<string, string> = {
  draft: 'default',
  reviewing: 'blue',
  pending_approval: 'gold',
  approved: 'green',
  rejected: 'red',
  done: 'green',
};

export default function DbReview() {
  const [form] = Form.useForm();
  const [connections, setConnections] = useState<DbConnectionItem[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [approveRow, setApproveRow] = useState<ChangeItem | null>(null);
  const [approveComment, setApproveComment] = useState('');
  const [approving, setApproving] = useState(false);

  const doRowApprove = async (approved: boolean) => {
    if (!approveRow?.thread_id) return;
    setApproving(true);
    try {
      await approveChange(approveRow.thread_id, {
        approved,
        comment: approveComment.trim() || undefined,
      });
      message.success(approved ? '已通过' : '已拒绝');
      setApproveRow(null);
      setApproveComment('');
      loadList(1);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setApproving(false);
    }
  };
  const [scriptFileId, setScriptFileId] = useState<number | undefined>();
  const [drillFileId, setDrillFileId] = useState<number | undefined>();
  const [uploading, setUploading] = useState<'script' | 'drill' | null>(null);

  const [list, setList] = useState<ChangeItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loadingList, setLoadingList] = useState(false);

  const loadConnections = () => {
    listDbConnections({ page_size: 200 })
      .then((r) => setConnections(r.items))
      .catch(() => setConnections([]));
  };

  const loadList = (targetPage = page) => {
    setLoadingList(true);
    listChanges({ page: targetPage, page_size: 20 })
      .then((r) => {
        setList(r.items);
        setTotal(r.total);
      })
      .catch(() => setList([]))
      .finally(() => setLoadingList(false));
  };

  useEffect(() => {
    loadConnections();
    loadList(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onConnectionChange = (id: string) => {
    const c = connections.find((x) => x.id === id);
    if (c) {
      form.setFieldsValue({ db_type: c.db_type, target_database: c.database });
    }
  };

  const onSubmit = async () => {
    const v = await form.validateFields();
    setSubmitting(true);
    setResult(null);
    try {
      const res = await submitChange({
        sql_text: v.sql_text,
        db_type: v.db_type,
        connection_id: v.connection_id,
        target_database: v.target_database,
        target_tables: v.target_tables,
        script_file_id: scriptFileId,
        drill_file_id: drillFileId,
      });
      setResult(res);
      if (res.ok) {
        message.success('评审完成');
        loadList(1);
      } else {
        message.error('评审未通过校验');
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const onApprove = async (approved: boolean) => {
    if (!result?.thread_id) return;
    try {
      // 审批上下文以库为准（刷新后内存 thread_id 会丢，从变更单详情取）
      let tid = result.thread_id;
      if (!tid && result.request_id) {
        try {
          const d = await getChange(result.request_id);
          tid = ((d?.request as Record<string, unknown> | undefined)?.thread_id as string) || '';
        } catch {
          /* 忽略，走下方提示 */
        }
      }
      if (!tid) {
        message.warning('未找到审批上下文（thread_id），请重新提交评审');
        return;
      }
      await approveChange(tid, { approved });
      message.success(approved ? '已通过' : '已拒绝');
      setResult((prev) => (prev ? { ...prev, status: approved ? 'approved' : 'rejected' } : prev));
      loadList(1);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Modal
        open={!!approveRow}
        title={`审批变更单 #${approveRow?.id ?? ''}`}
        confirmLoading={approving}
        onCancel={() => setApproveRow(null)}
        footer={
          <Space>
            <Button onClick={() => setApproveRow(null)}>取消</Button>
            <Button danger loading={approving} onClick={() => void doRowApprove(false)}>
              拒绝
            </Button>
            <Button type="primary" loading={approving} onClick={() => void doRowApprove(true)}>
              通过
            </Button>
          </Space>
        }
      >
        <Input.TextArea
          rows={3}
          value={approveComment}
          onChange={(e) => setApproveComment(e.target.value)}
          placeholder="审批意见（可选）"
        />
      </Modal>
      <Card title="数据库变更评审（db_review）">
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="只分析不执行：支持 DML/DDL 评审（不执行原 SQL），不支持事务；DML/查询可 EXPLAIN；MySQL 仅支持 InnoDB；禁止多语句。"
        />
        <Form form={form} layout="vertical" onFinish={() => void onSubmit()}>
          <Form.Item name="connection_id" label="数据源" rules={[{ required: true }]}>
            <Select
              placeholder="选择数据源"
              options={connections.map((c) => ({
                value: c.id,
                label: `${c.name}（${c.db_type} / ${c.database}）`,
              }))}
              onChange={onConnectionChange}
            />
          </Form.Item>
          <Space style={{ width: '100%' }} size={16} align="start">
            <Form.Item name="db_type" label="类型" rules={[{ required: true }]}>
              <Select
                style={{ width: 160 }}
                options={[
                  { value: 'postgresql', label: 'PostgreSQL' },
                  { value: 'mysql', label: 'MySQL' },
                ]}
              />
            </Form.Item>
            <Form.Item name="target_database" label="目标库">
              <Input style={{ width: 220 }} />
            </Form.Item>
            <Form.Item name="target_tables" label="目标表（可选）">
              <Select mode="tags" style={{ minWidth: 240 }} placeholder="表名，可多个" />
            </Form.Item>
          </Space>
          <Form.Item
            name="sql_text"
            label="SQL 脚本"
            rules={[{ required: true, message: '请输入 SQL 或上传 .sql 文件' }]}
          >
            <Input.TextArea rows={8} placeholder="粘贴 DDL/DML（评审只分析，不执行）" />
          </Form.Item>
          <Space style={{ marginBottom: 16 }} size={16}>
            <Upload
              accept=".sql,.txt"
              showUploadList={false}
              beforeUpload={(file) => {
                setUploading('script');
                uploadReviewFile(file, 'script', form.getFieldValue('db_type') || undefined)
                  .then((r) => {
                    setScriptFileId(r.file_id);
                    message.success('脚本已上传');
                  })
                  .catch((e) => message.error(e instanceof Error ? e.message : String(e)))
                  .finally(() => setUploading(null));
                return false;
              }}
            >
              <Button loading={uploading === 'script'}>
                {scriptFileId ? '重新上传脚本' : '上传 .sql 脚本'}
              </Button>
            </Upload>
            <Upload
              accept=".pdf"
              showUploadList={false}
              beforeUpload={(file) => {
                setUploading('drill');
                uploadReviewFile(file, 'drill', form.getFieldValue('db_type') || undefined)
                  .then((r) => {
                    setDrillFileId(r.file_id);
                    message.success('演练记录已上传');
                  })
                  .catch((e) => message.error(e instanceof Error ? e.message : String(e)))
                  .finally(() => setUploading(null));
                return false;
              }}
            >
              <Button loading={uploading === 'drill'}>
                {drillFileId ? '重新上传演练记录' : '上传演练记录 PDF'}
              </Button>
            </Upload>
            {scriptFileId ? <Tag color="blue">脚本已上传</Tag> : null}
            {drillFileId ? <Tag color="blue">演练已上传</Tag> : null}
          </Space>
          <Button type="primary" htmlType="submit" loading={submitting}>
            提交评审
          </Button>
        </Form>

        {result && !result.ok && (
          <Alert
            style={{ marginTop: 16 }}
            type="error"
            showIcon
            message="校验未通过"
            description={[...(result.errors ?? []), ...(result.warnings ?? [])].join('；')}
          />
        )}

        {result?.ok && (
          <Card type="inner" title="评审结果" style={{ marginTop: 16 }}>
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="变更单">{result.request_id ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="风险等级">
                {result.risk_level ? (
                  <Tag color={RISK_COLOR[result.risk_level] ?? 'default'}>{result.risk_level}</Tag>
                ) : (
                  '-'
                )}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_COLOR[result.status ?? ''] ?? 'default'}>{result.status}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="建议">
                {(result.suggestions ?? []).length > 0
                  ? (result.suggestions as string[]).join('；')
                  : '无'}
              </Descriptions.Item>
            </Descriptions>
            <Typography.Paragraph style={{ marginTop: 12, whiteSpace: 'pre-wrap' }}>
              {result.answer}
            </Typography.Paragraph>
            {result.metadata?.warnings ? (
              <Alert
                type="warning"
                showIcon
                message="元数据提示"
                description={(result.metadata.warnings as string[]).join('；')}
              />
            ) : null}
            {result.status === 'pending_approval' && result.thread_id && (
              <Space style={{ marginTop: 12 }}>
                <Button type="primary" onClick={() => void onApprove(true)}>
                  审批通过
                </Button>
                <Button danger onClick={() => void onApprove(false)}>
                  拒绝
                </Button>
              </Space>
            )}
          </Card>
        )}
      </Card>

      <Card title="变更单列表">
        <Table<ChangeItem>
          rowKey="id"
          loading={loadingList}
          dataSource={list}
          pagination={{
            current: page,
            pageSize: 20,
            total,
            onChange: (p) => {
              setPage(p);
              loadList(p);
            },
          }}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 80 },
            { title: '标题', dataIndex: 'title', ellipsis: true },
            { title: '目标库', dataIndex: 'target_database', width: 160 },
            { title: '类型', dataIndex: 'db_type', width: 110 },
            {
              title: '风险',
              dataIndex: 'risk_level',
              width: 100,
              render: (v: string | null) =>
                v ? <Tag color={RISK_COLOR[v] ?? 'default'}>{v}</Tag> : '-',
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 130,
              render: (v: string) => <Tag color={STATUS_COLOR[v] ?? 'default'}>{v}</Tag>,
            },
            {
              title: '操作',
              key: 'action',
              width: 100,
              render: (_: unknown, row: ChangeItem) =>
                row.status === 'pending_approval' && row.thread_id ? (
                  <Button size="small" type="primary" onClick={() => setApproveRow(row)}>
                    审批
                  </Button>
                ) : (
                  '-'
                ),
            },
            {
              title: '提交时间',
              dataIndex: 'create_at',
              width: 170,
              render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-'),
            },
          ]}
        />
      </Card>
    </Space>
  );
}
