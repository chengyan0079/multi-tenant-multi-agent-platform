/** 问答结果 + RAGAS 质量分析接口。 */
import { http } from './http';

export interface QaResultItem {
  id: string;
  trace_id: string | null;
  tenant_id: number;
  user_id: number;
  session_id: string;
  question: string;
  answer_mode: string | null;
  query_type: string | null;
  confidence: number | null;
  status: string;
  latency_ms: number | null;
  created_at: string;
}

export interface QaResultDetail extends QaResultItem {
  thread_id: string | null;
  agent_type: string;
  answer: string | null;
  retrieved_contexts: { doc_id: string; content: string; score: number; source?: string }[];
  sources: string[];
  reference_answer: string | null;
  token_usage: Record<string, number> | null;
  enable_web_search: boolean;
  error_msg: string | null;
  extra: Record<string, unknown> | null;
  updated_at: string;
}

export interface QaResultList {
  items: QaResultItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface RagasEval {
  id: string;
  qa_result_id: string;
  trace_id: string | null;
  tenant_id: number;
  evaluator: string;
  evaluator_model: string | null;
  dataset_version: string | null;
  faithfulness: number | null;
  answer_relevancy: number | null;
  context_precision: number | null;
  context_recall: number | null;
  answer_correctness: number | null;
  metrics: Record<string, unknown> | null;
  status: string;
  error_msg: string | null;
  eval_at: string | null;
  created_at: string;
  updated_at: string;
}

export const listQaResults = (params: {
  page?: number;
  page_size?: number;
  session_id?: string;
  status?: string;
} = {}) => {
  const qs = new URLSearchParams();
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  if (params.session_id) qs.set('session_id', params.session_id);
  if (params.status) qs.set('status', params.status);
  const s = qs.toString();
  return http.get<QaResultList>(`/api/v1/tenant/qa/results${s ? `?${s}` : ''}`);
};

export const getQaResult = (id: string) =>
  http.get<QaResultDetail>(`/api/v1/tenant/qa/results/${id}`);

/** 写入人工标准答案并触发 RAGAS 异步测评（202）。 */
export const submitQaReview = (id: string, referenceAnswer: string) =>
  http.post<{ eval_id: string; status: string }>(
    `/api/v1/tenant/qa/results/${id}/review`,
    { reference_answer: referenceAnswer },
  );

export const getQaQuality = (id: string) =>
  http.get<{ items: RagasEval[] }>(`/api/v1/tenant/qa/results/${id}/quality`);
