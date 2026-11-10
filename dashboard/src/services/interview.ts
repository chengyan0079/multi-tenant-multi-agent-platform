/** 面试助手：会话、SSE 流式对话与评估报告。 */
import { API_BASE, authHeaders, http } from './http';

export type InterviewStatus = 'in_progress' | 'finished' | 'failed';

export interface InterviewSessionItem {
  session_id: string;
  thread_id: string;
  target_position: string;
  status: InterviewStatus | string;
  overall_score: number | null;
  finished_at: string | null;
  created_at: string;
}

export interface InterviewSessionList {
  items: InterviewSessionItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface InterviewSessionDetail extends InterviewSessionItem {
  messages: { role: 'user' | 'assistant'; content: string }[];
}

export interface StartInterviewPayload {
  target_position: string;
  resume_review_id?: string | null;
}

export interface StartInterviewResult {
  session_id: string;
  thread_id: string;
  target_position: string;
  status: InterviewStatus | string;
  current_stage: string;
  message: string;
}

export interface InterviewReportSummary {
  overall_score: number;
  strengths: string[];
  improvements: string[];
}

export interface InterviewChatResult {
  session_id: string;
  reply: string;
  current_stage: string;
  total_turns: number;
  is_finished: boolean;
  report_summary?: InterviewReportSummary;
}

export interface InterviewDimension {
  dimension: string;
  score: number;
  comment: string;
  highlights: string[];
  weaknesses: string[];
}

export interface InterviewReport {
  session_id: string;
  thread_id: string;
  target_position: string;
  status: InterviewStatus | string;
  overall_score: number | null;
  dimensions: InterviewDimension[];
  strengths: string[];
  improvements: string[];
  overall_comment: string;
  recommended_topics: string[];
  next_step_advice: string;
  finished_at: string | null;
}

export const listInterviewSessions = (
  params: { page?: number; page_size?: number; status?: string } = {},
) => {
  const qs = new URLSearchParams();
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  if (params.status) qs.set('status', params.status);
  const s = qs.toString();
  return http.get<InterviewSessionList>(`/api/v1/tenant/interview/sessions${s ? `?${s}` : ''}`);
};

export const createInterviewSession = (payload: StartInterviewPayload) =>
  http.post<StartInterviewResult>('/api/v1/tenant/interview/sessions', payload);

export const getInterviewSession = (sessionId: string) =>
  http.get<InterviewSessionDetail>(`/api/v1/tenant/interview/sessions/${sessionId}`);

export const deleteInterviewSession = (sessionId: string) =>
  http.delete<{ session_id: string; status: string }>(
    `/api/v1/tenant/interview/sessions/${sessionId}`,
  );

export const stopInterviewChat = (sessionId: string) =>
  http.post<{ session_id: string; stopped: boolean }>(
    '/api/v1/tenant/interview/chat/stop',
    { session_id: sessionId },
  );

export const chatInterview = (sessionId: string, message: string) =>
  http.post<InterviewChatResult>(
    `/api/v1/tenant/interview/sessions/${sessionId}/chat`,
    { message },
  );

type RawInterviewReport = Omit<
  InterviewReport,
  'dimensions' | 'strengths' | 'improvements' | 'recommended_topics'
> & {
  dimensions: unknown;
  strengths: unknown;
  improvements: unknown;
  recommended_topics: unknown;
};

function parseArray<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value) as unknown;
      return Array.isArray(parsed) ? (parsed as T[]) : [];
    } catch {
      return [];
    }
  }
  return [];
}

export const getInterviewReport = async (sessionId: string): Promise<InterviewReport> => {
  const raw = await http.get<RawInterviewReport>(
    `/api/v1/tenant/interview/sessions/${sessionId}/report`,
  );
  return {
    ...raw,
    dimensions: parseArray<InterviewDimension>(raw.dimensions),
    strengths: parseArray<string>(raw.strengths),
    improvements: parseArray<string>(raw.improvements),
    recommended_topics: parseArray<string>(raw.recommended_topics),
  };
};

export interface InterviewStreamHandlers {
  onToken?: (content: string) => void;
  onDone?: (result: InterviewChatResult) => void;
  onStopped?: () => void;
  onError?: (message: string) => void;
}

/** POST SSE：后端只发 data: 行，事件类型 token / stopped / done / error。 */
export async function streamInterviewChat(
  sessionId: string,
  message: string,
  handlers: InterviewStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/v1/tenant/interview/sessions/${sessionId}/chat/stream`,
    {
      method: 'POST',
      headers: authHeaders({
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      }),
      body: JSON.stringify({ message }),
      signal,
    },
  );

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
  if (!res.body) throw new Error('当前浏览器不支持流式响应');

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let sawStopped = false;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');

    let boundary: number;
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const dataLine = frame.split('\n').find((line) => line.startsWith('data:'));
      if (!dataLine) continue;
      const text = dataLine.slice(5).trim();
      if (!text) continue;

      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(text) as Record<string, unknown>;
      } catch {
        continue;
      }

      if (payload.type === 'token') {
        handlers.onToken?.(String(payload.content ?? ''));
      } else if (payload.type === 'stopped') {
        sawStopped = true;
        handlers.onStopped?.();
      } else if (payload.type === 'done' && !sawStopped) {
        handlers.onDone?.({
          session_id: String(payload.session_id ?? sessionId),
          reply: String(payload.reply ?? ''),
          current_stage: String(payload.current_stage ?? ''),
          total_turns: Number(payload.total_turns ?? 0),
          is_finished: Boolean(payload.is_finished),
          report_summary: payload.report_summary
            ? (payload.report_summary as InterviewReportSummary)
            : undefined,
        });
      } else if (payload.type === 'error') {
        handlers.onError?.(String(payload.message ?? '流式输出异常'));
      }
    }
  }
}
