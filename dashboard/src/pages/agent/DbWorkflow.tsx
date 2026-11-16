import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Input,
  Select,
  Space,
  Steps,
  Tag,
  Typography,
  message,
} from 'antd';

import { listDbConnections, type DbConnectionItem } from '../../services/dbConnections';
import {
  advanceWorkflow,
  getWorkflow,
  submitChange,
  type WorkflowView,
} from '../../services/dbChange';

const STAGE_ORDER = ['submitted', 'pending_approval', 'approved', 'pending_gate', 'ready_for_prod'];

const STAGE_COLOR: Record<string, string> = {
  submitted: 'default',
  pending_approval: 'gold',
  approved: 'blue',
  pending_gate: 'gold',
  ready_for_prod: 'green',
  rejected: 'red',
  blocked: 'red',
  failed: 'red',
};

export default function DbWorkflow() {
  const [requestId, setRequestId] = useState<number | undefined>();
  const [view, setView] = useState<WorkflowView | null>(null);
  const [connections, setConnections] = useState<DbConnectionItem[]>([]);
  const [sandboxId, setSandboxId] = useState<string | undefined>();
  const [releaseThreadId, setReleaseThreadId] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);

  // 新提交
  const [sqlText, setSqlText] = useState('');
  const [dbType, setDbType] = useState('postgresql');
  const [connectionId, setConnectionId] = useState<string | undefined>();
  const [targetDatabase, setTargetDatabase] = useState('');

  useEffect(() => {
    listDbConnections({ page_size: 200 })
      .then((r) => setConnections(r.items ?? []))
      .catch(() => setConnections([]));
  }, []);

  const load = async (id: number) => {
    const v = await getWorkflow(id);
    setView(v);
    const reqThread = (v.request?.thread_id as string) || undefined;
    if (reqThread) setReleaseThreadId((prev) => prev ?? undefined);
    setRequestId(id);
  };

  const onSubmit = async () => {
    if (!sqlText.trim() || !connectionId) {
      message.warning('请填写 SQL 并选择数据源');
      return;
    }
    setBusy(true);
    try {
      const res = await submitChange({
        sql_text: sqlText,
        db_type: dbType,
        connection_id: connectionId,
        target_database: targetDatabase,
      });
      if (res.ok && res.request_id) {
        message.success('已提交评审');
        await load(res.request_id);
      } else {
        message.error((res.errors ?? []).join('；') || '提交失败');
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const doAction = async (action: string) => {
    if (!requestId) return;
    setBusy(true);
    try {
      const threadId =
        action === 'gate_approve' || action === 'gate_reject'
          ? releaseThreadId
          : ((view?.request?.thread_id as string) || undefined);
      const res = await advanceWorkflow(requestId, {
        action,
        thread_id: threadId,
        sandbox_connection_id: action === 'release' ? sandboxId : undefined,
      });
      if (res.ok === false) {
        message.error((res.error as string) || '推进失败');
      } else {
        message.success('已推进');
        if (res.thread_id) setReleaseThreadId(res.thread_id as string);
        if (res.final_sql) message.info('已输出 SQL（见下方详情）');
        await load(requestId);
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const currentStep = view ? STAGE_ORDER.indexOf(view.stage) : 0;
  const isTerminal = view && ['ready_for_prod', 'rejected', 'blocked', 'failed'].includes(view.stage);

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="数据库变更 · 统一业务编排">
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="流程：提交评审 → 人工审批 → 沙箱验证 → 人工放行 → 输出 SQL（平台不执行生产）"
        />
        {!view ? (
          <>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Space wrap>
                <Select
                  style={{ width: 300 }}
                  placeholder="数据源（评审/验证都用它）"
                  value={connectionId}
                  onChange={(v) => {
                    setConnectionId(v);
                    const c = connections.find((x) => x.id === v);
                    if (c) {
                      setDbType(c.db_type);
                      setTargetDatabase(c.database);
                    }
                  }}
                  options={connections.map((c) => ({
                    value: c.id,
                    label: `${c.name}（${c.db_type} / ${c.database} / ${c.env ?? 'prod'}）`,
                  }))}
                />
                <Select
                  style={{ width: 160 }}
                  value={dbType}
                  onChange={setDbType}
                  options={[
                    { value: 'postgresql', label: 'PostgreSQL' },
                    { value: 'mysql', label: 'MySQL' },
                  ]}
                />
                <Input
                  style={{ width: 200 }}
                  placeholder="目标库"
                  value={targetDatabase}
                  onChange={(e) => setTargetDatabase(e.target.value)}
                />
              </Space>
              <Input.TextArea
                rows={8}
                value={sqlText}
                onChange={(e) => setSqlText(e.target.value)}
                placeholder="粘贴 DDL/DML（评审只分析，不执行）"
              />
              <Space>
                <Button type="primary" loading={busy} onClick={() => void onSubmit()}>
                  提交评审
                </Button>
                <Input
                  style={{ width: 220 }}
                  placeholder="或输入已有变更单ID"
                  onPressEnter={(e) => {
                    const id = Number((e.target as HTMLInputElement).value);
                    if (id) void load(id);
                  }}
                />
              </Space>
            </Space>
          </>
        ) : (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Space>
              <Tag color={STAGE_COLOR[view.stage] ?? 'default'}>{view.stage}</Tag>
              <Typography.Text type="secondary">{view.stage_hint}</Typography.Text>
              <Button size="small" onClick={() => setView(null)}>
                重新开始
              </Button>
            </Space>

            <Steps
              current={Math.max(0, currentStep)}
              status={isTerminal && view.stage !== 'ready_for_prod' ? 'error' : 'process'}
              items={[
                { title: '提交' },
                { title: '审批' },
                { title: '评审通过' },
                { title: '沙箱验证' },
                { title: '放行/输出' },
              ]}
            />

            <Descriptions column={2} bordered size="small" title="变更单/评审/发布">
              <Descriptions.Item label="变更单">
                {String(view.request?.id ?? '-')} / {String(view.request?.target_database ?? '-')}
              </Descriptions.Item>
              <Descriptions.Item label="风险">
                {view.review?.risk_level ? (
                  <Tag color="red">{String(view.review.risk_level)}</Tag>
                ) : (
                  '-'
                )}
              </Descriptions.Item>
              <Descriptions.Item label="执行结果">
                {String(view.release?.exec_ok ?? '-')}
              </Descriptions.Item>
              <Descriptions.Item label="耗时(ms)">
                {String(view.release?.exec_ms ?? '-')}
              </Descriptions.Item>
              <Descriptions.Item label="最终 SQL" span={2}>
                <Typography.Paragraph copyable={{ text: String(view.release?.final_sql ?? '') }}>
                  {String(view.release?.final_sql ?? '-')}
                </Typography.Paragraph>
              </Descriptions.Item>
            </Descriptions>

            <Space wrap>
              {view.next_actions.includes('approve') && (
                <Button type="primary" loading={busy} onClick={() => void doAction('approve')}>
                  审批通过
                </Button>
              )}
              {view.next_actions.includes('reject') && (
                <Button danger loading={busy} onClick={() => void doAction('reject')}>
                  拒绝
                </Button>
              )}
              {view.next_actions.includes('release') && (
                <>
                  <Select
                    style={{ width: 260 }}
                    placeholder="选择沙箱数据源(env=sandbox)"
                    value={sandboxId}
                    onChange={setSandboxId}
                    options={connections
                      .filter((c) => (c.env ?? 'prod') === 'sandbox')
                      .map((c) => ({ value: c.id, label: `${c.name}（${c.database}）` }))}
                  />
                  <Button
                    type="primary"
                    loading={busy}
                    disabled={!sandboxId}
                    onClick={() => void doAction('release')}
                  >
                    沙箱验证
                  </Button>
                </>
              )}
              {view.next_actions.includes('gate_approve') && (
                <Button type="primary" loading={busy} onClick={() => void doAction('gate_approve')}>
                  放行输出 SQL
                </Button>
              )}
              {view.next_actions.includes('gate_reject') && (
                <Button danger loading={busy} onClick={() => void doAction('gate_reject')}>
                  拒绝放行
                </Button>
              )}
            </Space>
          </Space>
        )}
      </Card>
    </Space>
  );
}
