/** QA 问答助手：会话管理 + SSE 流式问答 + 停止生成。 */
import { API_BASE, authHeaders, http } from './http';

export interface QaSessionItem {
  thread_id: string;
  tenant_id: number;
  user_id: number;
  session_id: string;
  title: string;
  status: string;
  graph_name: string;
  created_at: string;
  updated_at: string;
}

export interface QaSessionDetail extends QaSessionItem {
  messages: { role: 'user' | 'assistant'; content: string }[];
}

export interface QaSessionList {
  items: QaSessionItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface QaSessionCreated {
  thread_id: string;
  session_id: string;
  title: string;
  status: string;
}

export const listQaSessions = (params: { page?: number; page_size?: number } = {}) => {
  const qs = new URLSearchParams();
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  const s = qs.toString();
  return http.get<QaSessionList>(`/api/v1/tenant/qa/sessions${s ? `?${s}` : ''}`);
};

export const createQaSession = (title = '新会话') =>
  http.post<QaSessionCreated>('/api/v1/tenant/qa/sessions', { title });

export const deleteQaSession = (threadId: string) =>
  http.delete<{ thread_id: string; status: string }>(
    `/api/v1/tenant/qa/sessions/${threadId}`,
  );

export const getQaSession = (threadId: string) =>
  http.get<QaSessionDetail>(`/api/v1/tenant/qa/sessions/${threadId}`);

export const stopQaChat = (sessionId: string) =>
  http.post<{ session_id: string; stopped: boolean }>('/api/v1/tenant/qa/chat/stop', {
    session_id: sessionId,
  });

export interface ChatStreamHandlers {
  onProgress?: (stage: string) => void;
  onToken?: (content: string) => void;
  onMeta?: (meta: {
    session_id: string;
    answer_mode: string;
    confidence: number;
    sources: string[];
  }) => void;
  onStopped?: () => void;
  onDone?: () => void;
  onError?: (message: string) => void;
}

/**
 * SSE 流式问答。
 * 停止策略（RAG-Ultra 为主 + rag-pro 兜底）：
 * - 调 stopQaChat() 写服务端停止标记，生成器在下一个事件前停止并发 stopped/done；
 * - 若 2s 内未收到 stopped/done，调用方 abort signal 兜底断连。
 */
export async function streamQaChat(
  params: { sessionId: string; message: string; enableWebSearch?: boolean },
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/tenant/qa/chat/stream`, {
    method: 'POST',
    headers: authHeaders({
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }),
    body: JSON.stringify({
      session_id: params.sessionId,
      message: params.message,
      enable_web_search: Boolean(params.enableWebSearch),
    }),
    signal,
  });

  if (!res.ok) {
    let msg = `请求失败：HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { msg?: string };
      if (body?.msg) msg = body.msg;
    } catch {
      /* 非 JSON 错误体忽略 */
    }
    throw new Error(msg);
  }
  if (!res.body) {
    throw new Error('当前浏览器不支持流式响应');
  }

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

      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(text) as Record<string, unknown>;
      } catch {
        continue;
      }
      switch (payload.type) {
        case 'progress':
          handlers.onProgress?.(String(payload.stage ?? ''));
          break;
        case 'token':
          handlers.onToken?.(String(payload.content ?? ''));
          break;
        case 'meta':
          handlers.onMeta?.({
            session_id: String(payload.session_id ?? params.sessionId),
            answer_mode: String(payload.answer_mode ?? ''),
            confidence: Number(payload.confidence ?? 0),
            sources: Array.isArray(payload.sources) ? (payload.sources as string[]) : [],
          });
          break;
        case 'stopped':
          handlers.onStopped?.();
          break;
        case 'done':
          handlers.onDone?.();
          break;
        case 'error':
          handlers.onError?.(String(payload.message ?? '流式输出异常'));
          break;
        default:
          break;
      }
    }
  }
}
