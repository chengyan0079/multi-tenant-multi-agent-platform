import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Empty, Input, Popover, Space, Tag, message } from 'antd';
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
} from '../../services/unified';
import { renderEvent, ROUTE_MAP } from './renderers';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  events: UnifiedEvent[];
  pending?: boolean;
}

const TOKEN_EVENTS = new Set(['token', 'progress', 'stopped', 'done']);

export default function UnifiedChat() {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<AgentCapability[]>([]);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [active, setActive] = useState<SessionItem | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [showEntry, setShowEntry] = useState(false);
  const [streaming, setStreaming] = useState(false);

  const controllerRef = useRef<StreamController | null>(null);
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
    try {
      const detail = await getUnifiedSession(s.thread_id);
      const msgs: ChatMessage[] = [];
      for (const t of detail.turns) {
        if (t.user_content) {
          msgs.push({ id: `${t.turn_index}-u`, role: 'user', content: t.user_content, events: [] });
        }
        if (t.assistant_content || t.event_type) {
          msgs.push({
            id: `${t.turn_index}-a`,
            role: 'assistant',
            content: t.assistant_content ?? '',
            events: t.event_type ? [{ type: t.event_type, ...t.payload } as UnifiedEvent] : [],
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
      const assistantMsg: ChatMessage = { id: assistantId, role: 'assistant', content: '', events: [] };
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
            agent_type: agentType,
            entry: entry ?? undefined,
            attachments: attachments && attachments.length ? attachments : undefined,
          },
          {
            onToken: (c) => appendToken(assistantId, c),
            onEvent: (e) => {
              if (TOKEN_EVENTS.has(e.type)) return;
              if (e.type === 'stopped' || e.type === 'done') controller.clearFallback();
              pushEvent(assistantId, e);
            },
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

  // 卡片点击：有入口表单/附件则展开表单，否则直接带 agent_type 发送
  const onCardClick = (spec: AgentCapability) => {
    setSelectedAgent(spec.agent_type);
    if (spec.entry_fields.length > 0 || spec.accept_files.length > 0) {
      setShowEntry(true);
    }
  };

  const onEntrySubmit = (entry: { name: string; value: string }[], fileRefs: string[]) => {
    pendingEntryRef.current = { entry, fileRefs };
    setShowEntry(false);
    // 入口型 Agent 填完即提交（无自由文本），否则聚焦输入框
    if (entry.length > 0 || fileRefs.length > 0) {
      void send('');
    }
  };

  const selectedSpec = agents.find((a) => a.agent_type === selectedAgent) ?? null;

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 220px)', background: '#fff' }}>
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
            <Empty description="选择一个能力卡片开始咨询" />
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
                <ChatBubble role={m.role} content={m.content} markdown={m.role === 'assistant'} />
                {m.events.map((e, i) => (
                  <div key={i}>{renderEvent(e, onAction)}</div>
                ))}
              </div>
            ))}
          </div>
        )}

        {showEntry && selectedSpec && (
          <EntryForm spec={selectedSpec} onCancel={() => setShowEntry(false)} onSubmit={onEntrySubmit} />
        )}

        <div style={{ borderTop: '1px solid #f0f0f0', padding: 12 }}>
          <div style={{ marginBottom: 8 }}>
            <Popover
              content={
                <div style={{ width: 240 }}>
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="工具调用能力待开发" />
                </div>
              }
              title="可用工具"
            >
              <Button type="text" size="small" icon={<ToolOutlined />}>
                工具
              </Button>
            </Popover>
          </div>
          <Space.Compact style={{ width: '100%' }}>
            <Input.TextArea
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
