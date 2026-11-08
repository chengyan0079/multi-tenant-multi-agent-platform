import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  App as AntdApp,
  Avatar,
  Button,
  Card,
  Empty,
  Input,
  List,
  Popconfirm,
  Result,
  Space,
  Spin,
  Switch,
  Typography,
} from 'antd';
import {
  DeleteOutlined,
  PlusOutlined,
  RobotOutlined,
  SendOutlined,
  StopOutlined,
  UserOutlined,
} from '@ant-design/icons';

import {
  createQaSession,
  deleteQaSession,
  getQaSession,
  listQaSessions,
  stopQaChat,
  streamQaChat,
  type QaSessionItem,
} from '../../../services/qa';
import { hasScope } from '../../../services/auth';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  streaming?: boolean;
}

const formatTime = (value: string): string =>
  (value || '').replace('T', ' ').slice(0, 16) || '-';

/**
 * QA 问答：左侧会话列表（后端会话接口），右侧 SSE 一问一答 + 停止输出。
 * 停止：服务端 Redis 停止标志（RAG-Ultra）+ 2s 未响应时 AbortController 兜底（rag-pro）。
 */
export default function QaChat() {
  const { message } = AntdApp.useApp();
  const [searchParams] = useSearchParams();
  const queryThreadId = searchParams.get('thread_id') ?? '';

  const [sessions, setSessions] = useState<QaSessionItem[]>([]);
  const [activeThreadId, setActiveThreadId] = useState('');
  const [messagesByThread, setMessagesByThread] = useState<Record<string, ChatMessage[]>>({});
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [webSearch, setWebSearch] = useState(false);
  const [stage, setStage] = useState('');
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const canPage = hasScope('qa_session:page');
  const canView = hasScope('qa_session:view');
  const canAdd = hasScope('qa_session:add');
  const canDelete = hasScope('qa_session:delete');
  const canAsk = hasScope('qa:ask');

  const activeSession = sessions.find((s) => s.thread_id === activeThreadId) ?? null;
  const messages = messagesByThread[activeThreadId] ?? [];

  const loadHistory = useCallback(
    async (threadId: string) => {
      setLoadingHistory(true);
      try {
        const detail = await getQaSession(threadId);
        setMessagesByThread((prev) => ({
          ...prev,
          [threadId]: detail.messages.map((m, index) => ({
            id: `${threadId}-${index}`,
            role: m.role,
            content: m.content,
          })),
        }));
      } catch (e) {
        message.error(e instanceof Error ? e.message : '会话历史加载失败');
      } finally {
        setLoadingHistory(false);
      }
    },
    [message],
  );

  const loadSessions = useCallback(
    async (preferred?: string) => {
      if (!canPage) return;
      setLoadingSessions(true);
      try {
        const res = await listQaSessions({ page: 1, page_size: 100 });
        setSessions(res.items);
        const target =
          preferred ||
          (queryThreadId && res.items.some((s) => s.thread_id === queryThreadId)
            ? queryThreadId
            : res.items[0]?.thread_id) ||
          '';
        setActiveThreadId(target);
        if (target) {
          void loadHistory(target);
        }
      } catch (e) {
        message.error(e instanceof Error ? e.message : '会话列表加载失败');
      } finally {
        setLoadingSessions(false);
      }
    },
    [canPage, loadHistory, message, queryThreadId],
  );

  const refreshSessions = useCallback(async () => {
    if (!canPage) return;
    try {
      const res = await listQaSessions({ page: 1, page_size: 100 });
      setSessions(res.items);
    } catch {
      /* 静默：标题刷新失败不影响对话 */
    }
  }, [canPage]);

  useEffect(() => {
    if (!canPage) return;
    void loadSessions();
  }, [canPage, loadSessions]);

  useEffect(() => {
    const el = listRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      if (stopTimerRef.current) {
        clearTimeout(stopTimerRef.current);
      }
    },
    [],
  );

  const createSession = async () => {
    if (!canAdd) return;
    try {
      const created = await createQaSession('新会话');
      const now = new Date().toISOString();
      const item: QaSessionItem = {
        thread_id: created.thread_id,
        session_id: created.session_id,
        title: created.title,
        status: created.status,
        tenant_id: 0,
        user_id: 0,
        graph_name: 'qa',
        created_at: now,
        updated_at: now,
      };
      setSessions((prev) => [item, ...prev]);
      setMessagesByThread((prev) => ({ ...prev, [created.thread_id]: [] }));
      setActiveThreadId(created.thread_id);
      setInput('');
    } catch (e) {
      message.error(e instanceof Error ? e.message : '新增会话失败');
    }
  };

  const removeSession = async (threadId: string) => {
    if (!canDelete) return;
    try {
      await deleteQaSession(threadId);
      if (threadId === activeThreadId) {
        abortRef.current?.abort();
      }
      const next = sessions.filter((s) => s.thread_id !== threadId);
      setSessions(next);
      setMessagesByThread((prev) => {
        const copy = { ...prev };
        delete copy[threadId];
        return copy;
      });
      if (threadId === activeThreadId) {
        const nextActive = next[0]?.thread_id ?? '';
        setActiveThreadId(nextActive);
        if (nextActive) {
          void loadHistory(nextActive);
        }
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : '删除会话失败');
    }
  };

  const selectSession = (threadId: string) => {
    if (threadId === activeThreadId) return;
    abortRef.current?.abort();
    setActiveThreadId(threadId);
    setInput('');
    if (!messagesByThread[threadId]) {
      void loadHistory(threadId);
    }
  };

  const stopStream = async () => {
    if (!streaming) return;
    setStopping(true);
    const sessionId = activeSession?.session_id;
    if (sessionId) {
      try {
        await stopQaChat(sessionId);
      } catch {
        /* 停止接口失败时仍走 abort 兜底 */
      }
    }
    if (stopTimerRef.current) {
      clearTimeout(stopTimerRef.current);
    }
    stopTimerRef.current = setTimeout(() => {
      abortRef.current?.abort();
    }, 2000);
  };

  const send = async () => {
    const text = input.trim();
    if (!text || streaming || !activeSession || !canAsk) return;

    const threadId = activeSession.thread_id;
    const sessionId = activeSession.session_id;
    const aiId = `a-${Date.now()}`;
    setMessagesByThread((prev) => ({
      ...prev,
      [threadId]: [
        ...(prev[threadId] ?? []),
        { id: `u-${Date.now()}`, role: 'user', content: text },
        { id: aiId, role: 'assistant', content: '', streaming: true },
      ],
    }));
    setInput('');
    setStreaming(true);
    setStopping(false);
    setStage('');

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamQaChat(
        { sessionId, message: text, enableWebSearch: webSearch },
        {
          onProgress: (value) => setStage(value),
          onToken: (chunk) => {
            setMessagesByThread((prev) => ({
              ...prev,
              [threadId]: (prev[threadId] ?? []).map((m) =>
                m.id === aiId ? { ...m, content: m.content + chunk } : m,
              ),
            }));
          },
          onStopped: () => message.info('已停止生成'),
          onError: (msg) => message.error(msg),
        },
        controller.signal,
      );
    } catch (e) {
      if ((e as Error)?.name === 'AbortError') {
        message.info('已停止生成');
      } else {
        message.error(e instanceof Error ? e.message : '问答失败');
      }
    } finally {
      if (stopTimerRef.current) {
        clearTimeout(stopTimerRef.current);
        stopTimerRef.current = null;
      }
      setMessagesByThread((prev) => ({
        ...prev,
        [threadId]: (prev[threadId] ?? []).map((m) =>
          m.id === aiId ? { ...m, streaming: false } : m,
        ),
      }));
      setStreaming(false);
      setStopping(false);
      setStage('');
      abortRef.current = null;
      // 后端首问会更新 agent_thread.title，刷新列表拿新标题
      void refreshSessions();
    }
  };

  if (!canPage || !canView) {
    return <Result status="403" title="无权限" subTitle="你没有访问问答会话的权限" />;
  }

  return (
    <Card
      title={<Typography.Title level={4} style={{ margin: 0 }}>QA问答</Typography.Title>}
      styles={{ body: { padding: 0 } }}
    >
      <div style={{ display: 'flex', height: 'calc(100vh - 220px)' }}>
        {/* 左侧：会话列表 */}
        <div
          style={{
            width: 280,
            flexShrink: 0,
            borderRight: '1px solid #f0f0f0',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div style={{ padding: 12, borderBottom: '1px solid #f0f0f0' }}>
            <Button
              type="primary"
              block
              icon={<PlusOutlined />}
              disabled={!canAdd}
              onClick={() => void createSession()}
            >
              新增会话
            </Button>
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            <Spin spinning={loadingSessions}>
              <List
                dataSource={sessions}
                locale={{ emptyText: '暂无会话' }}
                renderItem={(item) => (
                  <List.Item
                    onClick={() => selectSession(item.thread_id)}
                    style={{
                      cursor: 'pointer',
                      padding: '10px 12px',
                      background: item.thread_id === activeThreadId ? '#e6f4ff' : undefined,
                    }}
                    actions={
                      canDelete
                        ? [
                            <Popconfirm
                              key="del"
                              title="删除该会话？"
                              onConfirm={() => void removeSession(item.thread_id)}
                              okText="删除"
                              cancelText="取消"
                            >
                              <span onClick={(e) => e.stopPropagation()}>
                                <DeleteOutlined style={{ color: '#ff4d4f' }} />
                              </span>
                            </Popconfirm>,
                          ]
                        : []
                    }
                  >
                    <List.Item.Meta
                      title={<Typography.Text ellipsis>{item.title}</Typography.Text>}
                      description={
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {formatTime(item.updated_at)}
                        </Typography.Text>
                      }
                    />
                  </List.Item>
                )}
              />
            </Spin>
          </div>
        </div>

        {/* 右侧：聊天区 */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div style={{ padding: '8px 16px', borderBottom: '1px solid #f0f0f0' }}>
            <Space>
              <Typography.Text type="secondary">
                当前会话：{activeSession?.title ?? '未选择'}
              </Typography.Text>
              {stage ? (
                <Space size={6}>
                  <Spin size="small" />
                  <Typography.Text type="secondary">{stage}</Typography.Text>
                </Space>
              ) : null}
            </Space>
          </div>

          <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
            <Spin spinning={loadingHistory}>
              {!activeSession ? (
                <Empty description="请新建或选择一个会话" />
              ) : messages.length === 0 ? (
                <Empty description="输入问题开始对话" />
              ) : (
                messages.map((m) => (
                  <div
                    key={m.id}
                    style={{
                      display: 'flex',
                      justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
                      marginBottom: 12,
                    }}
                  >
                    <Space
                      align="start"
                      size={8}
                      style={{ flexDirection: m.role === 'user' ? 'row-reverse' : 'row' }}
                    >
                      <Avatar icon={m.role === 'user' ? <UserOutlined /> : <RobotOutlined />} />
                      <div
                        style={{
                          maxWidth: 640,
                          padding: '8px 12px',
                          borderRadius: 8,
                          whiteSpace: 'pre-wrap',
                          background: m.role === 'user' ? '#e6f4ff' : '#f5f5f5',
                        }}
                      >
                        {m.content ? (
                          m.content
                        ) : m.streaming ? (
                          <Space size={8}>
                            <Spin size="small" />
                            <Typography.Text type="secondary">
                              {stage || '思考中…'}
                            </Typography.Text>
                          </Space>
                        ) : null}
                      </div>
                    </Space>
                  </div>
                ))
              )}
            </Spin>
          </div>

          <div style={{ borderTop: '1px solid #f0f0f0', padding: 12 }}>
            <Input.TextArea
              value={input}
              disabled={!activeSession || !canAsk}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                !canAsk
                  ? '缺少 qa:ask 权限'
                  : activeSession
                    ? '输入问题，Enter 发送，Shift+Enter 换行'
                    : '请先新建或选择会话'
              }
              autoSize={{ minRows: 2, maxRows: 5 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginTop: 8,
              }}
            >
              <Space size={8}>
                <Typography.Text type="secondary">联网搜索</Typography.Text>
                <Switch
                  size="small"
                  checked={webSearch}
                  onChange={setWebSearch}
                  disabled={!canAsk}
                />
              </Space>
              {streaming ? (
                <Button
                  danger
                  icon={<StopOutlined />}
                  loading={stopping}
                  onClick={() => void stopStream()}
                >
                  {stopping ? '停止中…' : '停止输出'}
                </Button>
              ) : (
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  disabled={!activeSession || !canAsk || !input.trim()}
                  onClick={() => void send()}
                >
                  发送
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}
