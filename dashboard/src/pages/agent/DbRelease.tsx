import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';

import { listDbConnections, type DbConnectionItem } from '../../services/dbConnections';
import { listChanges, type ChangeItem } from '../../services/dbChange';
import {
  approveRelease,
  getRelease,
  releaseChange,
  type ReleaseResult,
} from '../../services/dbRelease';

const STATUS_COLOR: Record<string, string> = {
  verifying: 'blue',
  verified: 'blue',
  pending_gate: 'gold',
  ready_for_prod: 'green',
  rejected: 'red',
  blocked: 'red',
  failed: 'red',
};

export default function DbRelease() {
  const [connections, setConnections] = useState<DbConnectionItem[]>([]);
  const [approved, setApproved] = useState<ChangeItem[]>([]);
  const [requestId, setRequestId] = useState<number | undefined>();
  const [sandboxId, setSandboxId] = useState<string | undefined>();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ReleaseResult | null>(null);
  const [gateTarget, setGateTarget] = useState<{ requestId: number; threadId: string } | null>(
    null,
  );
  const [approving, setApproving] = useState(false);

  const load = () => {
    listDbConnections({ page_size: 200 })
      .then((r) => setConnections((r.items ?? []).filter((c) => (c.env ?? 'prod') === 'sandbox')))
      .catch(() => setConnections([]));
    listChanges({ status: 'approved', page_size: 200 })
      .then((r) => setApproved(r.items ?? []))
      .catch(() => setApproved([]));
  };

  useEffect(() => {
    load();
  }, []);

  // 行内审批：从 release 记录取 thread_id（库为准），仅 pending_gate 可审批
  const openRowGate = async (requestId: number) => {
    try {
      const row = await getRelease(requestId);
      const tid = (row?.thread_id as string) || '';
      if ((row?.status as string) !== 'pending_gate' || !tid) {
        message.info('该变更单暂无待放行记录');
        return;
      }
      setGateTarget({ requestId, threadId: tid });
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const doGateApprove = async (approved: boolean) => {
    if (!gateTarget) return;
    setApproving(true);
    try {
      await approveRelease(gateTarget.threadId, { approved });
      message.success(approved ? '已放行输出 SQL' : '已拒绝');
      setGateTarget(null);
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setApproving(false);
    }
  };

  const onRun = async () => {
    if (!requestId || !sandboxId) {
      message.warning('请选择已审批变更单与沙箱数据源');
      return;
    }
    setRunning(true);
    setResult(null);
    try {
      const res = await releaseChange(requestId, sandboxId, true);
      setResult(res);
      message.success('沙箱验证完成');
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const onApprove = async (approvedFlag: boolean) => {
    // 审批上下文以库为准（刷新后内存 thread_id 会丢，从 release 记录取）
    let tid = result?.thread_id;
    if (!tid && requestId) {
      try {
        const row = await getRelease(requestId);
        tid = (row?.thread_id as string) || undefined;
      } catch {
        /* 忽略，走下方提示 */
      }
    }
    if (!tid) {
      message.warning('未找到审批上下文（thread_id），请重新执行沙箱验证');
      return;
    }
    try {
      const res = await approveRelease(tid, { approved: approvedFlag });
      message.success(approvedFlag ? '已放行输出 SQL' : '已拒绝');
      setResult((prev) =>
        prev ? { ...prev, release_status: res.release_status, final_sql: res.final_sql } : prev,
      );
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const columns: ColumnsType<ChangeItem> = [
    { title: 'ID', dataIndex: 'id', width: 80 },
    { title: '标题', dataIndex: 'title', ellipsis: true },
    { title: '目标库', dataIndex: 'target_database', width: 160 },
    {
      title: '操作',
      width: 100,
      render: (_: unknown, r: ChangeItem) => (
        <Space>
          <Button type="link" size="small" onClick={() => setRequestId(r.id)}>
            选择
          </Button>
          <Button type="link" size="small" onClick={() => void openRowGate(r.id)}>
            审批
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Modal
        open={!!gateTarget}
        title="放行审批"
        confirmLoading={approving}
        onCancel={() => setGateTarget(null)}
        footer={
          <Space>
            <Button onClick={() => setGateTarget(null)}>取消</Button>
            <Button danger loading={approving} onClick={() => void doGateApprove(false)}>
              拒绝
            </Button>
            <Button type="primary" loading={approving} onClick={() => void doGateApprove(true)}>
              放行
            </Button>
          </Space>
        }
      >
        <div>确认放行变更单 #{gateTarget?.requestId} 的最终 SQL？</div>
      </Modal>
      <Card title="变更发布 · 沙箱验证（db_release）">
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="只在沙箱执行验证（env=sandbox，即用即弃回滚），不执行生产；通过后输出原样 SQL 由人工上生产。"
        />
        <Space wrap>
          <Select
            style={{ width: 320 }}
            placeholder="选择已审批变更单"
            value={requestId}
            onChange={setRequestId}
            options={approved.map((c) => ({
              value: c.id,
              label: `#${c.id} ${c.title || c.target_database}`,
            }))}
          />
          <Select
            style={{ width: 280 }}
            placeholder="选择沙箱数据源"
            value={sandboxId}
            onChange={setSandboxId}
            options={connections.map((c) => ({
              value: c.id,
              label: `${c.name}（${c.db_type} / ${c.database}）`,
            }))}
          />
          <Button type="primary" loading={running} onClick={() => void onRun()}>
            沙箱验证
          </Button>
        </Space>

        {result?.ok && (
          <Card type="inner" title="验证结果" style={{ marginTop: 16 }}>
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="状态">
                <Tag color={STATUS_COLOR[result.release_status ?? result.status ?? ''] ?? 'default'}>
                  {result.release_status ?? result.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="执行结果">
                {String((result.exec_result?.exec_ok as boolean) ?? '-')}
              </Descriptions.Item>
              <Descriptions.Item label="耗时(ms)">
                {String((result.exec_result?.exec_ms as number) ?? '-')}
              </Descriptions.Item>
              <Descriptions.Item label="影响行数">
                {String((result.exec_result?.affected_rows as number) ?? '-')}
              </Descriptions.Item>
              <Descriptions.Item label="已回滚">
                {String((result.exec_result?.rolled_back as boolean) ?? '-')}
              </Descriptions.Item>
              <Descriptions.Item label="错误">
                {(result.exec_result?.error as string) ?? '-'}
              </Descriptions.Item>
            </Descriptions>
            {result.answer && (
              <Typography.Paragraph style={{ marginTop: 12 }}>{result.answer}</Typography.Paragraph>
            )}
            {result.final_sql && (
              <>
                <Typography.Paragraph strong>最终 SQL（原样，供人工上生产）：</Typography.Paragraph>
                <Input.TextArea rows={6} readOnly value={result.final_sql} />
              </>
            )}
            {(result.status === 'pending_gate' || result.release_status === 'pending_gate') &&
              result.thread_id && (
                <Space style={{ marginTop: 12 }}>
                  <Button type="primary" onClick={() => void onApprove(true)}>
                    放行输出 SQL
                  </Button>
                  <Button danger onClick={() => void onApprove(false)}>
                    拒绝
                  </Button>
                </Space>
              )}
          </Card>
        )}

        {result && !result.ok && (
          <Alert style={{ marginTop: 16 }} type="error" showIcon message={result.answer ?? '校验未通过'} />
        )}
      </Card>

      <Card title="已审批变更单">
        <Table<ChangeItem>
          rowKey="id"
          dataSource={approved}
          columns={columns}
          pagination={{ pageSize: 10 }}
          size="small"
        />
      </Card>
    </Space>
  );
}
