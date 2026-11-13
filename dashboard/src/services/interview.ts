/** 面试助手：会话列表 / 报告查询（发起与流式对话已收口至统一咨询）。 */
import { http } from './http';

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

export const deleteInterviewSession = (sessionId: string) =>
  http.delete<{ session_id: string; status: string }>(
    `/api/v1/tenant/interview/sessions/${sessionId}`,
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
