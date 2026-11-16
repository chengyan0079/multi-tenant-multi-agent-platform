import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Card, Descriptions, Spin, Tag, Typography, message } from 'antd';
import ChatBubble from '../../components/ChatBubble';
import { getAdminSession, type SessionDetail, type TurnReplay } from '../../services/unified';
import { renderEvent, ROUTE_MAP } from './renderers';

interface ReplayMeta {
  answer_mode?: string;
  sources?: string[];
  latency_ms?: number;
  tokens?: number;
  tokensEstimated?: boolean;
}

interface ReplayMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  events: { type: string; [k: string]: unknown }[];
  meta?: ReplayMeta;
}

function toReplay(turns: TurnReplay[]): ReplayMessage[] {
  const out: ReplayMessage[] = [];
  for (const t of turns) {
    if (t.user_content) {
      out.push({ id: `${t.turn_index}-u`, role: 'user', content: t.user_content, events: [] });
    }
    if (t.assistant_content || t.event_type) {
      const p = (t.payload ?? {}) as Record<string, unknown>;
      const meta: ReplayMeta = {
        answer_mode: (p.answer_mode as string) || undefined,
        sources: Array.isArray(p.sources) ? (p.sources as string[]) : undefined,
        latency_ms: t.latency_ms ?? undefined,
        tokens: t.token_usage?.total,
        tokensEstimated: Boolean(
          (t.token_usage as { estimated?: boolean } | null)?.estimated,
        ),
      };
      out.push({
        id: `${t.turn_index}-a`,
        role: 'assistant',
        content: t.assistant_content ?? '',
        events: t.event_type ? [{ type: t.event_type, ...p }] : [],
        meta,
      });
    }
  }
  return out;
}

export default function UnifiedSessionDetail() {
  const { threadId } = useParams<{ threadId: string }>();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<SessionDetail | null>(null);

  const load = useCallback(async () => {
    if (!threadId) return;
    setLoading(true);
    try {
      setDetail(await getAdminSession(threadId));
    } catch {
      message.error('加载会话详情失败');
    } finally {
      setLoading(false);
    }
  }, [threadId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (!detail) {
    return <Typography.Text>会话不存在</Typography.Text>;
  }

  const onAction = (routeKey: string) => {
    const path = ROUTE_MAP[routeKey];
    if (path) navigate(path);
  };

  return (
    <div>
      <Button style={{ marginBottom: 12 }} onClick={() => navigate('/consultation/sessions')}>
        返回列表
      </Button>
      <Descriptions bordered size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="thread_id">
          <Typography.Text copyable>{detail.thread_id}</Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="标题">{detail.title || '未命名会话'}</Descriptions.Item>
        <Descriptions.Item label="会话键">{detail.session_id}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag>{detail.status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="Agent">
          {detail.agent_type ? <Tag color="blue">{detail.agent_type}</Tag> : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="轮数">{detail.turn_count}</Descriptions.Item>
      </Descriptions>
      <Card title="报告式汇总" size="small" style={{ marginBottom: 16 }}>
        <Descriptions bordered size="small" column={3}>
          <Descriptions.Item label="总轮次">{detail.turn_count}</Descriptions.Item>
          <Descriptions.Item label="用户消息">
            {detail.turns.filter((t) => t.user_content).length}
          </Descriptions.Item>
          <Descriptions.Item label="助手回复">
            {detail.turns.filter((t) => t.assistant_content).length}
          </Descriptions.Item>
          <Descriptions.Item label="总 tokens（全会话累计）">
            {(() => {
              // 优先用后端聚合值（覆盖全部轮次，不受回放分页限制）
              const aggregated = detail.total_tokens ?? 0;
              const fromTurns = detail.turns.reduce(
                (acc, t) => acc + (t.token_usage?.total ?? 0),
                0,
              );
              const total = aggregated || fromTurns;
              const estimated = detail.turns.some(
                (t) => (t.token_usage as { estimated?: boolean } | null)?.estimated,
              );
              return total ? `${estimated ? '≈' : ''}${total}` : '-';
            })()}
          </Descriptions.Item>
          <Descriptions.Item label="平均耗时">
            {(() => {
              const vals = detail.turns
                .map((t) => t.latency_ms)
                .filter((v): v is number => v != null);
              return vals.length
                ? `${(vals.reduce((a, b) => a + b, 0) / vals.length / 1000).toFixed(2)}s`
                : '-';
            })()}
          </Descriptions.Item>
          <Descriptions.Item label="涉及 Agent">
            {Array.from(new Set(detail.turns.map((t) => t.agent_type).filter(Boolean))).map(
              (a) => (
                <Tag key={a as string} color="blue">
                  {a as string}
                </Tag>
              ),
            )}
          </Descriptions.Item>
          <Descriptions.Item label="执行状态">
            {Object.entries(
              detail.turns.reduce<Record<string, number>>((acc, t) => {
                const st = String((t.payload as Record<string, unknown>)?.status ?? t.status);
                acc[st] = (acc[st] ?? 0) + 1;
                return acc;
              }, {}),
            ).map(([k, v]) => (
              <Tag key={k}>
                {k} × {v}
              </Tag>
            ))}
          </Descriptions.Item>
          <Descriptions.Item label="风险分布">
            {(() => {
              const risks = detail.turns.reduce<Record<string, number>>((acc, t) => {
                const rk = (t.payload as Record<string, unknown>)?.risk_level;
                if (rk) acc[String(rk)] = (acc[String(rk)] ?? 0) + 1;
                return acc;
              }, {});
              const entries = Object.entries(risks);
              return entries.length === 0
                ? '-'
                : entries.map(([k, v]) => (
                    <Tag key={k} color={k === 'low' ? 'green' : 'red'}>
                      {k} × {v}
                    </Tag>
                  ));
            })()}
          </Descriptions.Item>
        </Descriptions>
      </Card>
      <Card title="对话回放">
        {detail.turns.length === 0 ? (
          <Typography.Text type="secondary">该会话暂无可回放的对话记录</Typography.Text>
        ) : null}
        {toReplay(detail.turns).map((m) => (
          <div key={m.id}>
            <ChatBubble role={m.role} content={m.content} markdown={m.role === 'assistant'} />
            {m.meta ? (
              <div className="uc-meta">
                {m.meta.answer_mode ? (
                  <Tag color="blue">
                    出处：
                    {m.meta.answer_mode === 'rag'
                      ? '知识库检索'
                      : m.meta.answer_mode === 'web_search' || m.meta.answer_mode === 'web'
                        ? '网络搜索'
                        : '直接回答'}
                  </Tag>
                ) : null}
                {(m.meta.sources ?? []).slice(0, 3).map((s) => (
                  <Tag key={s}>{s.length > 28 ? `${s.slice(0, 28)}…` : s}</Tag>
                ))}
                {m.meta.latency_ms != null ? (
                  <Tag color="gold">耗时 {(m.meta.latency_ms / 1000).toFixed(2)}s</Tag>
                ) : null}
                {m.meta.tokens ? (
                  <Tag color="purple">
                    tokens {m.meta.tokensEstimated ? '≈' : ''}
                    {m.meta.tokens}
                  </Tag>
                ) : null}
              </div>
            ) : null}
            {m.events.map((e, i) => (
              <div key={i}>{renderEvent(e as never, onAction)}</div>
            ))}
          </div>
        ))}
      </Card>
    </div>
  );
}
