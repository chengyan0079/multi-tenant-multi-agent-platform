/**
 * 统一咨询入口 service 层（§9.3）。
 *
 * 覆盖 12 个 /unified/* 端点的客户端封装：能力卡片、会话 CRUD、附件两阶段上传、
 * 流式问答（SSE）、停止。SSE 解析与 qa.ts 同范式，但帧结构为 UnifiedEvent
 * （type + payload 平铺字段），且 401 复用 http.handleUnauthorized 跳登录。
 */
import { API_BASE, authHeaders, handleUnauthorized, http } from './http';

// --------------------------------------------------------------------------- //
// 类型（与后端 unified_dtos / unified_schemas 对齐）
// --------------------------------------------------------------------------- //

export interface AgentCard {
  icon: string;
  badge: string;
  sort_order: number;
  action_label: string;
}

export interface EntryField {
  name: string;
  label: string;
  type: 'str' | 'int' | 'float' | 'bool' | 'uuid' | 'enum';
  required: boolean;
  default?: string | number | boolean | null;
  options?: string[] | null;
}

export interface AgentCapability {
  agent_type: string;
  display_name: string;
  description: string;
  card: AgentCard | null;
  templates: string[];
  entry_fields: EntryField[];
  accept_files: string[];
  route_key: string;
  tags: string[];
}

export interface SessionItem {
  thread_id: string;
  session_id: string;
  title: string;
  status: string;
  agent_type: string;
  turn_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface SessionList {
  items: SessionItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface TurnReplay {
  turn_index: number;
  agent_type: string;
  event_type: string;
  user_content: string | null;
  assistant_content: string | null;
  payload: Record<string, unknown>;
  status: string;
  error_code: string | null;
  create_at: string | null;
}

export interface SessionDetail extends SessionItem {
  turns: TurnReplay[];
}

export interface AttachmentRef {
  file_ref: string;
  filename: string;
  size: number;
  content_type: string;
}

export interface ArtifactItem {
  artifact_type: string;
  artifact_id: string;
  route_key: string;
}

export interface ArtifactList {
  items: ArtifactItem[];
  total: number;
}

/** SSE 帧：type 为事件名，其余字段平铺自 payload（与后端 {"type":..., **payload} 一致）。 */
export type UnifiedEvent = { type: string } & Record<string, unknown>;

export interface UnifiedChatParams {
  session_id: string;
  message: string;
  agent_type?: string | null;
  /** 入口字段校验结果：[{ name, value }]，按 spec.entry_fields 收集 */
  entry?: { name: string; value: string }[];
  /** 两阶段上传拿到的 file_ref 列表 */
  attachments?: string[];
}

export interface StreamHandlers {
  onEvent?: (e: UnifiedEvent) => void;
  onToken?: (content: string) => void;
  onDone?: () => void;
  onStopped?: () => void;
  onError?: (message: string) => void;
}

// --------------------------------------------------------------------------- //
// 能力卡片 / 会话 CRUD / 附件
// --------------------------------------------------------------------------- //

export const getUnifiedAgents = () => http.get<AgentCapability[]>('/api/v1/tenant/unified/agents');

export const listUnifiedSessions = (params: { page?: number; page_size?: number } = {}) => {
  const qs = new URLSearchParams();
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  const s = qs.toString();
  return http.get<SessionList>(`/api/v1/tenant/unified/sessions${s ? `?${s}` : ''}`);
};

export const createUnifiedSession = (body: { session_id?: string; title?: string } = {}) =>
  http.post<SessionDetail>('/api/v1/tenant/unified/sessions', body);

export const getUnifiedSession = (threadId: string) =>
  http.get<SessionDetail>(`/api/v1/tenant/unified/sessions/${threadId}`);

export const deleteUnifiedSession = (threadId: string) =>
  http.delete<{ deleted: number }>(`/api/v1/tenant/unified/sessions/${threadId}`);

export const getSessionArtifacts = (threadId: string) =>
  http.get<ArtifactList>(`/api/v1/tenant/unified/sessions/${threadId}/artifacts`);

// 管理端：跨用户（仅按租户），需 unified_session:page/view/delete
export const listAdminSessions = (params: { page?: number; page_size?: number; status?: string } = {}) => {
  const qs = new URLSearchParams();
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  if (params.status) qs.set('status', params.status);
  const s = qs.toString();
  return http.get<SessionList>(`/api/v1/tenant/unified/session-admin/sessions${s ? `?${s}` : ''}`);
};

export const getAdminSession = (threadId: string) =>
  http.get<SessionDetail>(`/api/v1/tenant/unified/session-admin/sessions/${threadId}`);

export const deleteAdminSession = (threadId: string) =>
  http.delete<{ deleted: number }>(`/api/v1/tenant/unified/session-admin/sessions/${threadId}`);

/** 两阶段上传第一步：返回 file_ref，后续随 chat 请求带上。 */
export async function uploadAttachment(file: File, agentType?: string): Promise<AttachmentRef> {
  const form = new FormData();
  form.append('file', file);
  if (agentType) form.append('agent_type', agentType);
  const res = await fetch(`${API_BASE}/api/v1/tenant/unified/attachments`, {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  });
  if (!res.ok) {
    if (res.status === 401) handleUnauthorized();
    let msg = `上传失败：HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { msg?: string };
      if (body?.msg) msg = body.msg;
    } catch {
      /* 非 JSON 错误体忽略 */
    }
    throw new Error(msg);
  }
  const env = (await res.json()) as { code: number; msg: string; data: AttachmentRef };
  if (env.code !== 0) throw new Error(env.msg || '上传失败');
  return env.data;
}

export const stopUnifiedChat = (sessionId: string) =>
  http.post<{ ok: boolean }>('/api/v1/tenant/unified/chat/stop', { session_id: sessionId });

// --------------------------------------------------------------------------- //
// SSE 流式
// --------------------------------------------------------------------------- //

/** 把 SSE 响应体解析为 UnifiedEvent 序列，逐帧回调 onEvent。 */
export async function parseSseStream(
  res: Response,
  onEvent: (e: UnifiedEvent) => void,
): Promise<void> {
  if (!res.body) throw new Error('当前浏览器不支持流式响应');
  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, '\n');
    let boundary: number;
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const dataLine = raw.split('\n').find((line) => line.startsWith('data:'));
      if (!dataLine) continue;
      const text = dataLine.slice(5).trim();
      if (!text || text === '[DONE]') continue;
      let payload: UnifiedEvent;
      try {
        payload = JSON.parse(text) as UnifiedEvent;
      } catch {
        continue; // 解析失败的帧跳过，不阻断消息流
      }
      onEvent(payload);
    }
  }
}

/**
 * 流式问答（显式/隐式通道统一走 /unified/chat/stream）。
 * 停止策略：调 stopUnifiedChat 写服务端标记，2s 内未收到 stopped/done 则由调用方 abort 兜底。
 */
export async function streamUnifiedChat(
  params: UnifiedChatParams,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/tenant/unified/chat/stream`, {
    method: 'POST',
    headers: authHeaders({
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }),
    body: JSON.stringify({
      session_id: params.session_id,
      message: params.message,
      agent_type: params.agent_type ?? null,
      entry: params.entry ? { fields: params.entry } : null,
      attachments: (params.attachments ?? []).map((file_ref) => ({ file_ref })),
    }),
    signal,
  });

  if (!res.ok) {
    if (res.status === 401) handleUnauthorized();
    let msg = `请求失败：HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { msg?: string };
      if (body?.msg) msg = body.msg;
    } catch {
      /* 非 JSON 错误体忽略 */
    }
    throw new Error(msg);
  }

  await parseSseStream(res, (e) => {
    handlers.onEvent?.(e);
    switch (e.type) {
      case 'token':
        handlers.onToken?.(String(e.content ?? ''));
        break;
      case 'stopped':
        handlers.onStopped?.();
        break;
      case 'done':
        handlers.onDone?.();
        break;
      case 'error':
        handlers.onError?.(String(e.message ?? '流式输出异常'));
        break;
      default:
        break;
    }
  });
}
