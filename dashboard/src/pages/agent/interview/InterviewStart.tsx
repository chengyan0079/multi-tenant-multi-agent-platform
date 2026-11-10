import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  App as AntdApp,
  Avatar,
  Button,
  Card,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Result,
  Select,
  Space,
  Spin,
  Tag,
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
  createInterviewSession,
  deleteInterviewSession,
  getInterviewSession,
  listInterviewSessions,
  stopInterviewChat,
  streamInterviewChat,
  type InterviewChatResult,
  type InterviewReportSummary,
  type InterviewSessionItem,
  type StartInterviewPayload,
} from '../../../services/interview';
import { listResumes } from '../../../services/resume';
import { hasScope } from '../../../services/auth';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  streaming?: boolean;
}

const STATUS_COLOR: Record<string, string> = {
  in_progress: 'processing',
  finished: 'success',
  failed: 'error',
  deleted: 'default',
};
const STATUS_LABEL: Record<string, string> = {
  in_progress: '进行中',
  finished: '已结束',
  failed: '失败',
  deleted: '已删除',
};
const STAGE_LABEL: Record<string, string> = {
  warmup: '热身',
  tech_base: '技术基础',
  project: '项目深挖',
  closing: '反问收尾',
  finished: '已结束',
};

const formatTime = (value: string | null): string =>
  value ? value.replace('T', ' ').slice(0, 16) : '-';

const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

/** 开始面试：左侧会话栏，右侧 SSE 聊天栏；历史回放/软删/服务端停止生成对齐 QA。 */
export default function InterviewStart() {
  const { message: toast } = AntdApp.useApp();
  const navigate = useNavigate();
  const [form] = Form.useForm<StartInterviewPayload>();

  const canPage = hasScope('interview:page');
  const canAsk = hasScope('interview:ask');
  const canView = hasScope('interview:view');
  const canDelete = hasScope('interview:delete');

  const [sessions, setSessions] = useState<InterviewSessionItem[]>([]);
  const [activeId, setActiveId] = useState('');
  const [messagesBySession, setMessagesBySession] = useState<Record<string, ChatMessage[]>>({});
  const [summaries, setSummaries] = useState<Record<string, InterviewReportSummary>>({});
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stage, setStage] = useState('');
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [startOpen, setStartOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const [resumeOptions, setResumeOptions] = useState<{ value: string; label: string }[]>([]);

  const abortRef = useRef<AbortController | null>(null);
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const activeSession = sessions.find((item) => item.session_id === activeId) ?? null;
  const messages = messagesBySession[activeId] ?? [];
  const summary = summaries[activeId];

  const clearStopTimer = useCallback(() => {
    if (stopTimerRef.current) {
      clearTimeout(stopTimerRef.current);
      stopTimerRef.current = null;
    }
  }, []);

  const loadSessions = useCallback(
    async (preferred?: string) => {
      if (!canPage) return;
      setLoadingSessions(true);
      try {
        const res = await listInterviewSessions({ page: 1, page_size: 100 });
        setSessions(res.items);
        const target = preferred || activeId || res.items[0]?.session_id || '';
        setActiveId(target);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : '面试会话列表加载失败');
      } finally {
        setLoadingSessions(false);
      }
    },
    [activeId, canPage, toast],
  );

  const loadHistory = useCallback(
    async (sessionId: string) => {
      setLoadingHistory(true);
      try {
        if (!canView) {
          setMessagesBySession((prev) => ({
            ...prev,
            [sessionId]: [
              {
                id: uid(),
                role: 'assistant',
                content: '缺少 interview:view 权限，无法回放历史消息。',
              },
            ],
          }));
          return;
        }
        const detail = await getInterviewSession(sessionId);
        setMessagesBySession((prev) => ({
          ...prev,
          [sessionId]: detail.messages.map((item, index) => ({
            id: `${sessionId}-${index}`,
            role: item.role,
            content: item.content,
          })),
        }));
      } catch (e) {
        toast.error(e instanceof Error ? e.message : '历史消息加载失败');
        setMessagesBySession((prev) => ({
          ...prev,
          [sessionId]: [
            {
              id: uid(),
              role: 'assistant',
              content: '历史消息加载失败，可继续当前面试。',
            },
          ],
        }));
      } finally {
        setLoadingHistory(false);
      }
    },
    [canView, toast],
  );

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    if (!activeId || messagesBySession[activeId]) return;
    void loadHistory(activeId);
  }, [activeId, messagesBySession, loadHistory]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      clearStopTimer();
    },
    [clearStopTimer],
  );

  const openStart = () => {
    form.resetFields();
    form.setFieldsValue({ target_position: '软件工程师', resume_review_id: undefined });
    setStartOpen(true);
    void listResumes({ page: 1, page_size: 100 })
      .then((res) => {
        setResumeOptions(
          res.items
            .filter((item) => item.status === 'done')
            .map((item) => ({
              value: item.review_id,
              label: `${item.review_id.slice(0, 8)}… · ${formatTime(item.created_at)}`,
            })),
        );
      })
      .catch(() => setResumeOptions([]));
  };

  const submitStart = async () => {
    if (!canAsk) return;
    try {
      const values = await form.validateFields();
      setStarting(true);
      const created = await createInterviewSession({
        target_position: values.target_position.trim(),
        resume_review_id: values.resume_review_id || null,
      });
      setMessagesBySession((prev) => ({
        ...prev,
        [created.session_id]: [
          {
            id: uid(),
            role: 'assistant',
            content: created.message || '面试已开始，请先做自我介绍。',
          },
        ],
      }));
      setActiveId(created.session_id);
      setStartOpen(false);
      toast.success('面试已创建');
      await loadSessions(created.session_id);
    } catch (e) {
      if (e instanceof Error) toast.error(e.message);
      else if (e && typeof e === 'object' && 'errorFields' in e) return;
      else toast.error('创建面试失败');
    } finally {
      setStarting(false);
    }
  };

  const selectSession = (sessionId: string) => {
    if (streaming) abortRef.current?.abort();
    setActiveId(sessionId);
    setInput('');
  };

  const removeSession = async (sessionId: string) => {
    if (!canDelete) return;
    try {
      if (sessionId === activeId && streaming) abortRef.current?.abort();
      await deleteInterviewSession(sessionId);
      toast.success('面试会话已删除');
      setMessagesBySession((prev) => {
        const next = { ...prev };
        delete next[sessionId];
        return next;
      });
      setSummaries((prev) => {
        const next = { ...prev };
        delete next[sessionId];
        return next;
      });
      const remaining = sessions.filter((item) => item.session_id !== sessionId);
      setSessions(remaining);
      if (activeId === sessionId) setActiveId(remaining[0]?.session_id ?? '');
      void loadSessions(remaining[0]?.session_id);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '删除面试会话失败');
    }
  };

  const stopStream = async () => {
    if (!activeSession || !streaming || stopping) return;
    setStopping(true);
    try {
      await stopInterviewChat(activeSession.session_id);
    } catch (e) {
      toast.warning(e instanceof Error ? e.message : '停止标记写入失败，将本地中断');
    }
    clearStopTimer();
    stopTimerRef.current = setTimeout(() => abortRef.current?.abort(), 2000);
  };

  const applyDone = (sessionId: string, result: InterviewChatResult, aiId: string) => {
    setMessagesBySession((prev) => ({
      ...prev,
      [sessionId]: (prev[sessionId] ?? []).map((item) =>
        item.id === aiId
          ? {
              ...item,
              content:
                item.content ||
                (result.is_finished ? '本轮面试已结束，报告已生成。' : result.reply || ''),
              streaming: false,
            }
          : item,
      ),
    }));
    setStage(STAGE_LABEL[result.current_stage] || result.current_stage);
    if (result.report_summary) {
      setSummaries((prev) => ({ ...prev, [sessionId]: result.report_summary! }));
    }
    setSessions((prev) =>
      prev.map((item) =>
        item.session_id === sessionId
          ? {
              ...item,
              status: result.is_finished ? 'finished' : item.status,
              overall_score: result.report_summary?.overall_score ?? item.overall_score,
            }
          : item,
      ),
    );
    void loadSessions(sessionId);
  };

  const send = async () => {
    const text = input.trim();
    if (!activeSession || !canAsk || !text || streaming) return;
    if (activeSession.status !== 'in_progress') {
      toast.warning('该面试已结束，请查看报告');
      return;
    }

    const sessionId = activeSession.session_id;
    const userMsg: ChatMessage = { id: uid(), role: 'user', content: text };
    const aiMsg: ChatMessage = { id: uid(), role: 'assistant', content: '', streaming: true };
    setMessagesBySession((prev) => ({
      ...prev,
      [sessionId]: [...(prev[sessionId] ?? []), userMsg, aiMsg],
    }));
    setInput('');
    setStreaming(true);
    setStage('面试官思考中…');

    const controller = new AbortController();
    abortRef.current = controller;
    let serverStopped = false;

    try {
      await streamInterviewChat(
        sessionId,
        text,
        {
          onToken: (chunk) => {
            setMessagesBySession((prev) => ({
              ...prev,
              [sessionId]: (prev[sessionId] ?? []).map((item) =>
                item.id === aiMsg.id ? { ...item, content: item.content + chunk } : item,
              ),
            }));
          },
          onDone: (result) => applyDone(sessionId, result, aiMsg.id),
          onStopped: () => {
            serverStopped = true;
            clearStopTimer();
            setStopping(false);
            setMessagesBySession((prev) => ({
              ...prev,
              [sessionId]: (prev[sessionId] ?? []).map((item) =>
                item.id === aiMsg.id
                  ? { ...item, content: item.content || '已停止生成', streaming: false }
                  : item,
              ),
            }));
          },
          onError: (msg) => {
            toast.error(msg);
            setMessagesBySession((prev) => ({
              ...prev,
              [sessionId]: (prev[sessionId] ?? []).map((item) =>
                item.id === aiMsg.id
                  ? { ...item, content: item.content || `流式输出异常：${msg}`, streaming: false }
                  : item,
              ),
            }));
          },
        },
        controller.signal,
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : '流式面试请求失败';
      if (msg.includes('aborted') || (e as Error)?.name === 'AbortError') {
        if (!serverStopped) toast.info('已停止生成');
        setMessagesBySession((prev) => ({
          ...prev,
          [sessionId]: (prev[sessionId] ?? []).map((item) =>
            item.id === aiMsg.id
              ? { ...item, content: item.content || '已停止生成', streaming: false }
              : item,
          ),
        }));
      } else {
        toast.error(msg);
        setMessagesBySession((prev) => ({
          ...prev,
          [sessionId]: (prev[sessionId] ?? []).map((item) =>
            item.id === aiMsg.id
              ? { ...item, content: item.content || `请求失败：${msg}`, streaming: false }
              : item,
          ),
        }));
      }
    } finally {
      clearStopTimer();
      setStreaming(false);
      setStopping(false);
      setStage('');
      abortRef.current = null;
    }
  };

  if (!canPage || !canAsk) {
    return <Result status="403" title="无权限" subTitle="你没有开始面试的权限" />;
  }

  return (
    <Card
      title={<Typography.Title level={4} style={{ margin: 0 }}>开始面试</Typography.Title>}
      styles={{ body: { padding: 0 } }}
    >
      <div style={{ display: 'flex', height: 'calc(100vh - 220px)' }}>
        <div
          style={{
            width: 300,
            flexShrink: 0,
            borderRight: '1px solid #f0f0f0',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div style={{ padding: 12, borderBottom: '1px solid #f0f0f0' }}>
            <Button type="primary" block icon={<PlusOutlined />} onClick={openStart}>
              新建面试
            </Button>
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            <Spin spinning={loadingSessions}>
              <List
                dataSource={sessions}
                locale={{ emptyText: '暂无面试会话' }}
                renderItem={(item) => (
                  <List.Item
                    onClick={() => selectSession(item.session_id)}
                    style={{
                      cursor: 'pointer',
                      padding: '10px 12px',
                      background: item.session_id === activeId ? '#e6f4ff' : undefined,
                    }}
                    actions={
                      canDelete
                        ? [
                            <Popconfirm
                              key="del"
                              title="删除该面试会话？"
                              description="软删归档，历史不会立即展示。"
                              onConfirm={() => void removeSession(item.session_id)}
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
                      title={
                        <Space size={6}>
                          <Typography.Text ellipsis style={{ maxWidth: 150 }}>
                            {item.target_position}
                          </Typography.Text>
                          <Tag color={STATUS_COLOR[item.status] ?? 'default'}>
                            {STATUS_LABEL[item.status] ?? item.status}
                          </Tag>
                        </Space>
                      }
                      description={
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {formatTime(item.created_at)}
                          {item.overall_score != null ? ` · ${item.overall_score} 分` : ''}
                        </Typography.Text>
                      }
                    />
                  </List.Item>
                )}
              />
            </Spin>
          </div>
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div style={{ padding: '8px 16px', borderBottom: '1px solid #f0f0f0' }}>
            <Space wrap>
              <Typography.Text type="secondary">
                当前面试：{activeSession?.target_position ?? '未选择'}
              </Typography.Text>
              {activeSession ? (
                <Tag color={STATUS_COLOR[activeSession.status] ?? 'default'}>
                  {STATUS_LABEL[activeSession.status] ?? activeSession.status}
                </Tag>
              ) : null}
              {stage ? (
                <Space size={6}>
                  {streaming ? <Spin size="small" /> : null}
                  <Typography.Text type="secondary">{stage}</Typography.Text>
                </Space>
              ) : null}
            </Space>
          </div>

          <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
            <Spin spinning={loadingHistory}>
              {!activeSession ? (
                <Empty description="请新建或选择一个面试会话" />
              ) : (
                <>
                  {summary ? (
                    <Alert
                      type="success"
                      showIcon
                      style={{ marginBottom: 12 }}
                      message={`面试结束，综合得分 ${summary.overall_score}`}
                      description={
                        <Space direction="vertical" size={2}>
                          <span>优势：{summary.strengths.join('；') || '暂无'}</span>
                          <span>改进：{summary.improvements.join('；') || '暂无'}</span>
                        </Space>
                      }
                      action={
                        canView ? (
                          <Button
                            size="small"
                            onClick={() => navigate(`/agent/interview/results/${activeId}`)}
                          >
                            查看报告
                          </Button>
                        ) : undefined
                      }
                    />
                  ) : null}
                  {activeSession.status === 'finished' && canView ? (
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginBottom: 12 }}
                      message="面试已结束"
                      action={
                        <Button
                          size="small"
                          onClick={() => navigate(`/agent/interview/results/${activeId}`)}
                        >
                          面试报告
                        </Button>
                      }
                    />
                  ) : null}
                  {messages.length === 0 ? (
                    <Empty description="输入回答开始面试" />
                  ) : (
                    messages.map((item) => (
                      <div
                        key={item.id}
                        style={{
                          display: 'flex',
                          justifyContent: item.role === 'user' ? 'flex-end' : 'flex-start',
                          marginBottom: 12,
                        }}
                      >
                        <Space
                          align="start"
                          size={8}
                          style={{ flexDirection: item.role === 'user' ? 'row-reverse' : 'row' }}
                        >
                          <Avatar icon={item.role === 'user' ? <UserOutlined /> : <RobotOutlined />} />
                          <div
                            style={{
                              maxWidth: 680,
                              padding: '8px 12px',
                              borderRadius: 8,
                              whiteSpace: 'pre-wrap',
                              background: item.role === 'user' ? '#e6f4ff' : '#f5f5f5',
                            }}
                          >
                            {item.content || (
                              <Space size={8}>
                                <Spin size="small" />
                                <Typography.Text type="secondary">
                                  {stage || '面试官思考中…'}
                                </Typography.Text>
                              </Space>
                            )}
                          </div>
                        </Space>
                      </div>
                    ))
                  )}
                </>
              )}
            </Spin>
          </div>

          <div style={{ borderTop: '1px solid #f0f0f0', padding: 12 }}>
            <Input.TextArea
              value={input}
              disabled={!activeSession || activeSession.status !== 'in_progress' || !canAsk}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                !activeSession
                  ? '请先新建或选择面试会话'
                  : activeSession.status !== 'in_progress'
                    ? '面试已结束，可查看报告'
                    : '输入回答，Enter 发送，Shift+Enter 换行'
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
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                输入「结束面试」可提前进入报告生成
              </Typography.Text>
              {streaming ? (
                <Button
                  danger
                  icon={<StopOutlined />}
                  loading={stopping}
                  onClick={() => void stopStream()}
                >
                  {stopping ? '停止中…' : '停止生成'}
                </Button>
              ) : (
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  disabled={
                    !activeSession ||
                    activeSession.status !== 'in_progress' ||
                    !canAsk ||
                    !input.trim()
                  }
                  onClick={() => void send()}
                >
                  发送回答
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>

      <Modal
        title="新建模拟面试"
        open={startOpen}
        onCancel={() => setStartOpen(false)}
        onOk={() => void submitStart()}
        okText="开始面试"
        confirmLoading={starting}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="target_position"
            label="目标岗位"
            rules={[{ required: true, message: '请输入目标岗位' }]}
          >
            <Input placeholder="如：AI 应用开发工程师" maxLength={128} />
          </Form.Item>
          <Form.Item
            name="resume_review_id"
            label="关联简历评审（可选）"
            extra="选择已完成评审后，面试会结合简历项目深挖；不选则按通用面试流程。"
          >
            <Select
              allowClear
              placeholder="不关联简历"
              options={resumeOptions}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
