import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Empty, Input, Modal, Popover, Space, Switch, Tag, message } from 'antd';
import { streamUnifiedResume } from '../../services/unified';
import { ArrowRightOutlined, BulbOutlined, PauseOutlined, ToolOutlined } from '@ant-design/icons';
import ChatBubble from '../../components/ChatBubble';
import SessionList from '../../components/SessionList';
import { StreamController } from '../../components/StreamController';
import EntryForm from '../../components/EntryForm';
import {
  type AgentCapability,
  type SessionItem,
  type UnifiedEvent,
  createUnifiedSession,
  deleteUnifiedSession,
  getUnifiedAgents,
  getUnifiedSession,
  listUnifiedSessions,
  stopUnifiedChat,
  streamUnifiedChat,
  getUnifiedTools,
  setUnifiedToolEnabled,
  type UnifiedToolItem,
} from '../../services/unified';
import { renderEvent, ROUTE_MAP } from './renderers';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  events: UnifiedEvent[];
  pending?: boolean;
  /** 思考过程（思考模式开启时由 reasoning 事件累加） */
  reasoning?: string;
  /** 历史回放用：出处/耗时/tokens（流式时来自 meta 事件） */
  meta?: {
    answer_mode?: string;
    sources?: string[];
    latency_ms?: number;
    tokens?: number;
    /** true=字符估算（模型未返回 usage） */
    tokensEstimated?: boolean;
  };
}

/** 业务 Agent（db_review/db_release）统一咨询返回的结果卡片 */
interface ResultCard {
  agent_type: string;
  thread_id: string;
  request_id?: number;
  risk_level?: string;
  status?: string;
  final_sql?: string | null;
  answer?: string;
  suggestions?: string[];
  latency_ms?: number;
  token_usage?: {
    prompt?: number;
    completion?: number;
    total?: number;
    estimated?: boolean;
  };
}

const TOKEN_EVENTS = new Set(['token', 'progress', 'stopped', 'done']);

export default function UnifiedChat() {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<AgentCapability[]>([]);
  const [tools, setTools] = useState<UnifiedToolItem[]>([]);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [active, setActive] = useState<SessionItem | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [showEntry, setShowEntry] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [cardsVisible, setCardsVisible] = useState(true);
  const [activeCard, setActiveCard] = useState<ResultCard | null>(null);
  const [approveOpen, setApproveOpen] = useState(false);
  const [approveComment, setApproveComment] = useState('');
  const [approving, setApproving] = useState(false);
  const [thinking, setThinking] = useState(false);

  const controllerRef = useRef<StreamController | null>(null);
  const assistantIdRef = useRef<string>('');
  const inputRef = useRef<{ focus: () => void } | null>(null);
  const pendingEntryRef = useRef<{ entry: { name: string; value: string }[]; fileRefs: string[] } | null>(
    null,
  );

  const loadAgents = useCallback(async () => {
    try {
      setAgents(await getUnifiedAgents());
    } catch {
      /* 卡片加载失败不阻断聊天，仅空态无卡片 */
    }
  }, []);

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const r = await listUnifiedSessions({ page: 1, page_size: 50 });
      setSessions(r.items);
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAgents();
    loadSessions();
    // 当前租户可用工具（后端读内存注册表）
    getUnifiedTools()
      .then(setTools)
      .catch(() => setTools([]));
  }, [loadAgents, loadSessions]);

  const onAction = useCallback(
    (routeKey: string) => {
      const path = ROUTE_MAP[routeKey];
      if (path) navigate(path);
    },
    [navigate],
  );

  const selectSession = useCallback(async (s: SessionItem) => {
    setActive(s);
    setMessages([]);
    setCardsVisible(true);
    try {
      const detail = await getUnifiedSession(s.thread_id);
      const msgs: ChatMessage[] = [];
      for (const t of detail.turns) {
        if (t.user_content) {
          msgs.push({ id: `${t.turn_index}-u`, role: 'user', content: t.user_content, events: [] });
        }
        if (t.assistant_content || t.event_type) {
          const p = (t.payload ?? {}) as Record<string, unknown>;
          msgs.push({
            id: `${t.turn_index}-a`,
            role: 'assistant',
            content: t.assistant_content ?? '',
            events: t.event_type ? [{ type: t.event_type, ...p } as UnifiedEvent] : [],
            meta: {
              answer_mode: (p.answer_mode as string) || undefined,
              sources: Array.isArray(p.sources) ? (p.sources as string[]) : undefined,
              latency_ms: (t.latency_ms as number | null) ?? undefined,
              tokens: (t.token_usage as { total?: number } | null)?.total,
              tokensEstimated: Boolean(
                (t.token_usage as { estimated?: boolean } | null)?.estimated,
              ),
            },
          });
        }
      }
      setMessages(msgs);
    } catch {
      message.error('加载会话详情失败');
    }
  }, []);

  const newSession = useCallback(async () => {
    try {
      const s = await createUnifiedSession();
      setActive(s);
      setMessages([]);
      setCardsVisible(true);
      await loadSessions();
    } catch {
      message.error('新建会话失败');
    }
  }, [loadSessions]);

  const deleteSession = useCallback(
    async (s: SessionItem) => {
      try {
        await deleteUnifiedSession(s.thread_id);
        if (active?.thread_id === s.thread_id) {
          setActive(null);
          setMessages([]);
        }
        await loadSessions();
      } catch {
        message.error('删除会话失败');
      }
    },
    [active, loadSessions],
  );

  const appendToken = (id: string, c: string) =>
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, content: m.content + c } : m)));

  const pushEvent = (id: string, e: UnifiedEvent) =>
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, events: [...m.events, e] } : m)));

  const send = useCallback(
    async (text?: string) => {
      const content = text ?? input;
      if (!content.trim() && !pendingEntryRef.current) return;
      if (streaming) return;

      let sessionKey = active?.session_id;
      if (!sessionKey) {
        try {
          const s = await createUnifiedSession();
          sessionKey = s.session_id;
          setActive(s);
          await loadSessions();
        } catch {
          message.error('创建会话失败');
          return;
        }
      }

      const agentType = selectedAgent;
      const entry = pendingEntryRef.current?.entry;
      const attachments = pendingEntryRef.current?.fileRefs;

      const userMsg: ChatMessage = { id: `u-${Date.now()}`, role: 'user', content, events: [] };
      const assistantId = `a-${Date.now()}`;
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        events: [],
        pending: true,
      };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setInput('');
      pendingEntryRef.current = null;
      setShowEntry(false);
      setSelectedAgent(null);
      setStreaming(true);

      const controller = new StreamController();
      controllerRef.current = controller;

      try {
        await streamUnifiedChat(
          {
            session_id: sessionKey,
            message: content,
            thinking,
            agent_type: agentType,
            entry: entry ?? undefined,
            attachments: attachments && attachments.length ? attachments : undefined,
          },
          {
            onToken: (c) => appendToken(assistantId, c),
            onEvent: (e) => {
              if (TOKEN_EVENTS.has(e.type)) return;
              if (e.type === 'stopped' || e.type === 'done') controller.clearFallback();
              if (e.type === 'interrupt') {
                // HITL 打断：聊天框内弹审批框（通过/驳回后继续流式，不用刷新）
                setActiveCard({
                  agent_type: String(e.agent_type ?? ''),
                  thread_id: String(e.thread_id ?? ''),
                  request_id: e.request_id as number | undefined,
                  risk_level: e.risk_level as string | undefined,
                  status: String(e.agent_type) === 'db_review' ? 'pending_approval' : 'pending_gate',
                  answer: e.answer as string | undefined,
                });
                assistantIdRef.current = assistantId;
                setApproveOpen(true);
                return;
              }
              if (e.type === 'result_card') {
                // 正文已由流式 token 输出，这里只更新结果卡片（不覆盖正文）
                setActiveCard(e as unknown as ResultCard);
                return;
              }
              if (e.type === 'orchestration_result') {
                // 并行编排结果（qa 规范 + db_review 评审）：拼成文本直接展示
                const res = (e.result ?? {}) as Record<string, any>;
                const par = (res.parallel ?? {}) as Record<string, any>;
                const qa = par.qa?.answer ?? '';
                const rv = par.db_review ?? {};
                const risk = rv.risk_level ?? '-';
                const sug = Array.isArray(rv.suggestions) ? rv.suggestions.join('；') : '';
                const text =
                  `【规范问答】\n${qa || '（无）'}\n\n【变更评审】\n风险等级：${risk}` +
                  (sug ? `\n优化建议：${sug}` : '');
                setMessages((prev) =>
                  prev.map((m) => (m.id === assistantId ? { ...m, content: text } : m)),
                );
                return;
              }
              pushEvent(assistantId, e);
            },
            onReasoning: (c) =>
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, reasoning: `${m.reasoning ?? ''}${c}` }
                    : m,
                ),
              ),
            onStopped: () => controller.clearFallback(),
            onDone: () => controller.clearFallback(),
            onError: (msg) => pushEvent(assistantId, { type: 'error', message: msg }),
          },
          controller.signal(),
        );
      } catch (err) {
        if (!(err instanceof DOMException && err.name === 'AbortError')) {
          message.error(err instanceof Error ? err.message : '流式请求失败');
        }
      } finally {
        setStreaming(false);
        controllerRef.current = null;
        // 流结束（正常/中断/异常）都要关掉加载态
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, pending: false } : m)),
        );
        await loadSessions();
      }
    },
    [active, input, selectedAgent, streaming, loadSessions],
  );

  const stop = useCallback(() => {
    const key = active?.session_id;
    if (!key || !controllerRef.current) return;
    controllerRef.current.stop(() => stopUnifiedChat(key));
  }, [active]);

  // 卡片点击：有入口表单/附件则展开表单；否则收起卡片区，只保留示例问题，直接去输入框提问
  const onCardClick = (spec: AgentCapability) => {
    setSelectedAgent(spec.agent_type);
    if (spec.entry_fields.length > 0 || spec.accept_files.length > 0) {
      setShowEntry(true);
      return;
    }
    setCardsVisible(false);
    inputRef.current?.focus();
  };

  const onEntrySubmit = (entry: { name: string; value: string }[], fileRefs: string[]) => {
    pendingEntryRef.current = { entry, fileRefs };
    setShowEntry(false);
    // 入口型 Agent 填完即提交（无自由文本），否则聚焦输入框
    if (entry.length > 0 || fileRefs.length > 0) {
      void send('');
    }
  };

  const doApprove = async (approved: boolean) => {
    if (!activeCard) return;
    setApproving(true);
    try {
      // 审批后继续真流式（同一消息追加 token，无需刷新）
      await streamUnifiedResume(
        {
          thread_id: activeCard.thread_id,
          agent_type: activeCard.agent_type,
          approved,
          comment: approveComment.trim() || undefined,
        },
        {
          onToken: (c) =>
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantIdRef.current
                  ? { ...m, content: m.content + c, pending: true }
                  : m,
              ),
            ),
          onError: (msg) => message.error(msg),
        },
      );
      message.success(approved ? '已通过' : '已拒绝');
      setActiveCard({ ...activeCard, status: approved ? 'done' : 'rejected' });
      setApproveOpen(false);
      setApproveComment('');
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setApproving(false);
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantIdRef.current ? { ...m, pending: false } : m)),
      );
    }
  };

  const toggleTool = async (id: string, enabled: boolean) => {
    try {
      await setUnifiedToolEnabled(id, enabled);
      setTools((prev) => prev.map((t) => (t.id === id ? { ...t, enabled } : t)));
      message.success(enabled ? '已启用' : '已停用');
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const selectedSpec = agents.find((a) => a.agent_type === selectedAgent) ?? null;

  return (
    <div className="uc-shell" style={{ display: 'flex', height: 'calc(100vh - 220px)' }}>
      <div style={{ width: 280, borderRight: '1px solid #f0f0f0', overflow: 'auto' }}>
        <SessionList
          loading={sessionsLoading}
          sessions={sessions}
          activeId={active?.thread_id ?? null}
          onSelect={selectSession}
          onNew={newSession}
          onDelete={deleteSession}
        />
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {messages.length === 0 && !showEntry ? (
          <div style={{ padding: 24, overflow: 'auto' }}>
            <Empty
              description={
                cardsVisible ? '选择一个能力卡片开始咨询' : '已进入对话，请在下方输入问题'
              }
            />
            {cardsVisible && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 16 }}>
              {agents.map((a) => (
                <Card
                  key={a.agent_type}
                  hoverable
                  style={{ width: 220, height: 200 }}
                  extra={a.card?.badge ? <Tag color="blue">{a.card.badge}</Tag> : undefined}
                  onClick={() => onCardClick(a)}
                >
                  <Card.Meta
                    title={a.display_name}
                    description={
                      <div
                        style={{
                          display: '-webkit-box',
                          WebkitLineClamp: 3,
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                        }}
                      >
                        {a.description}
                      </div>
                    }
                  />
                  <div style={{ marginTop: 12, color: '#1677ff', fontSize: 13 }}>
                    {a.card?.action_label ?? '点击咨询'} <ArrowRightOutlined />
                  </div>
                </Card>
              ))}
            </div>
            )}
            {(() => {
              const tpls = agents.flatMap((a) => a.templates);
              if (!tpls.length) return null;
              return (
                <div style={{ marginTop: 24, maxWidth: 560 }}>
                  <div style={{ marginBottom: 10, color: '#888', fontSize: 13 }}>或者，挑一个常见问题开始</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {tpls.map((tpl, i) => (
                      <div
                        key={i}
                        onClick={() => {
                          setSelectedAgent(
                            agents.find((a) => a.templates.includes(tpl))?.agent_type ?? null,
                          );
                          setInput(tpl);
                        }}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 8,
                          padding: '9px 12px',
                          background: '#fafafa',
                          border: '1px solid #f0f0f0',
                          borderRadius: 8,
                          cursor: 'pointer',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = '#f0f5ff';
                          e.currentTarget.style.borderColor = '#bcd4ff';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = '#fafafa';
                          e.currentTarget.style.borderColor = '#f0f0f0';
                        }}
                      >
                        <BulbOutlined style={{ color: '#faad14' }} />
                        <span style={{ flex: 1 }}>{tpl}</span>
                        <ArrowRightOutlined style={{ color: '#bfbfbf' }} />
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}
          </div>
        ) : (
          <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
            {messages.map((m) => (
              <div key={m.id}>
                {m.role === 'assistant' && m.reasoning ? (
                  <details className="uc-think" open={!!m.pending}>
                    <summary>
                      <BulbOutlined />
                      {m.pending ? '正在思考…' : `已深度思考（${m.reasoning.length} 字）`}
                    </summary>
                    <div className="uc-think-body">{m.reasoning}</div>
                  </details>
                ) : null}
                <ChatBubble role={m.role} content={m.content} markdown={m.role === 'assistant'} />
                {m.role === 'assistant' && m.pending ? (
                  m.content ? (
                    <div className="uc-caret-line">
                      <span className="uc-caret" />
                    </div>
                  ) : (
                    <div className="uc-typing" aria-label="正在生成">
                      <span />
                      <span />
                      <span />
                    </div>
                  )
                ) : null}
                {m.role === 'assistant'
                  ? (() => {
                      const evMeta = [...m.events].reverse().find((e) => e.type === 'meta') as
                        | (UnifiedEvent & {
                            answer_mode?: string;
                            sources?: string[];
                            latency_ms?: number;
                            token_usage?: { total?: number; estimated?: boolean };
                          })
                        | undefined;
                      // 历史回放：meta 来自 turn 行；实时流式：meta 来自 meta 事件
                      const meta = m.meta
                        ? {
                            answer_mode: m.meta.answer_mode,
                            sources: m.meta.sources,
                            latency_ms: m.meta.latency_ms,
                            token_usage: {
                              total: m.meta.tokens,
                              estimated: m.meta.tokensEstimated,
                            },
                          }
                        : evMeta;
                      if (!meta) return null;
                      const modeText =
                        meta.answer_mode === 'rag'
                          ? '知识库检索'
                          : meta.answer_mode === 'web_search' || meta.answer_mode === 'web'
                            ? '网络搜索'
                            : '直接回答';
                      const srcs = (meta.sources ?? []).slice(0, 3);
                      return (
                        <div className="uc-meta">
                          <Tag color="blue">出处：{modeText}</Tag>
                          {srcs.map((s) => (
                            <Tag key={s}>{s.length > 28 ? `${s.slice(0, 28)}…` : s}</Tag>
                          ))}
                          {meta.latency_ms != null ? (
                            <Tag color="gold">
                              耗时 {(meta.latency_ms / 1000).toFixed(2)}s
                            </Tag>
                          ) : null}
                          {meta.token_usage?.total ? (
                            <Tag color="purple">
                              tokens {meta.token_usage.estimated ? '≈' : ''}
                              {meta.token_usage.total}
                            </Tag>
                          ) : null}
                        </div>
                      );
                    })()
                  : null}
                {m.events.map((e, i) => (
                  <div key={i}>{renderEvent(e, onAction)}</div>
                ))}
              </div>
            ))}
          </div>
        )}

        {activeCard && (
          <Card
            className="uc-card"
            size="small"
            style={{ margin: '0 24px 12px' }}
            title={activeCard.agent_type === 'db_review' ? '变更评审结果' : '变更发布结果'}
          >
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <Space>
                {activeCard.risk_level && (
                  <span>
                    风险等级：
                    <Tag color={activeCard.risk_level === 'low' ? 'green' : 'red'}>
                      {activeCard.risk_level}
                    </Tag>
                  </span>
                )}
                <span>
                  状态：<Tag color={activeCard.status === 'done' ? 'green' : 'gold'}>{activeCard.status}</Tag>
                </span>
                {activeCard.latency_ms != null ? (
                  <Tag color="gold">耗时 {(activeCard.latency_ms / 1000).toFixed(2)}s</Tag>
                ) : null}
                {activeCard.token_usage?.total ? (
                  <Tag color="purple">
                    tokens {activeCard.token_usage.estimated ? '≈' : ''}
                    {activeCard.token_usage.total}
                  </Tag>
                ) : null}
              </Space>
              {activeCard.answer ? <div>{activeCard.answer}</div> : null}
              {activeCard.suggestions && activeCard.suggestions.length > 0 ? (
                <div style={{ color: '#666' }}>建议：{activeCard.suggestions.join('；')}</div>
              ) : null}
              {activeCard.final_sql ? (
                <Input.TextArea rows={4} readOnly value={activeCard.final_sql} />
              ) : null}
              <Space>
                {(activeCard.status === 'pending_approval' ||
                  activeCard.status === 'pending_gate') && (
                  <Button type="primary" onClick={() => setApproveOpen(true)}>
                    审批
                  </Button>
                )}
                <Button
                  onClick={() =>
                    navigate(
                      activeCard.agent_type === 'db_review'
                        ? '/agent/db-review'
                        : '/agent/db-release',
                    )
                  }
                >
                  查看详情
                </Button>
              </Space>
            </Space>
          </Card>
        )}

        <Modal
          open={approveOpen}
          title="审批"
          confirmLoading={approving}
          onCancel={() => setApproveOpen(false)}
          footer={
            <Space>
              <Button onClick={() => setApproveOpen(false)}>取消</Button>
              <Button danger loading={approving} onClick={() => void doApprove(false)}>
                拒绝
              </Button>
              <Button type="primary" loading={approving} onClick={() => void doApprove(true)}>
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

        {showEntry && selectedSpec && (
          <EntryForm spec={selectedSpec} onCancel={() => setShowEntry(false)} onSubmit={onEntrySubmit} />
        )}

        <div style={{ borderTop: '1px solid #f0f0f0', padding: 12 }}>
          <div style={{ marginBottom: 8 }}>
            <Popover
              content={
                <div style={{ width: 280 }}>
                  {tools.length === 0 ? (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="当前租户暂无已启用工具"
                    />
                  ) : (
                    <div className="uc-tool-list">
                      {tools.map((t) => (
                        <div className="uc-tool-item" key={t.id}>
                          <span className={`uc-tool-dot ${t.enabled ? '' : 'is-off'}`} />
                          <div style={{ flex: 1 }}>
                            <div className="uc-tool-name">{t.name}</div>
                            {t.description ? (
                              <div className="uc-tool-desc">{t.description}</div>
                            ) : null}
                          </div>
                          <Switch
                            size="small"
                            checked={t.enabled}
                            onChange={(v) => void toggleTool(t.id, v)}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              }
              title="可用工具"
            >
              <Button type="text" size="small" icon={<ToolOutlined />}>
                工具
              </Button>
            </Popover>
            <span
              style={{
                marginLeft: 10,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                verticalAlign: 'middle',
              }}
            >
              <Switch size="small" checked={thinking} onChange={setThinking} />
              <span
                style={{
                  fontSize: 12,
                  color: thinking ? 'var(--brand)' : '#8c8c8c',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                }}
              >
                <BulbOutlined />
                思考模式
              </span>
            </span>
          </div>
          <Space.Compact style={{ width: '100%' }}>
            <Input.TextArea
              ref={(node) => {
                inputRef.current = node ? { focus: () => node.focus() } : null;
              }}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入消息，Enter 发送 / Shift+Enter 换行"
              autoSize={{ minRows: 1, maxRows: 4 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
              disabled={streaming}
            />
            {streaming ? (
              <Button danger icon={<PauseOutlined />} onClick={stop}>
                暂停输出
              </Button>
            ) : (
              <Button type="primary" onClick={() => void send()}>
                发送
              </Button>
            )}
          </Space.Compact>
        </div>
      </div>
    </div>
  );
}
