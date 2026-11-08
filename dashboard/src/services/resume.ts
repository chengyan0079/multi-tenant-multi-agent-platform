/** 简历评审接口（后端 /api/v1/tenant/resume；按租户 + 用户隔离，超管无权限）。 */

import { API_BASE, ApiError, authHeaders, http, type ApiEnvelope } from './http';

/** 后端状态：上传后 processing，save_results 节点写 done，失败 failed，默认 pending。 */
export type ResumeStatus = 'pending' | 'processing' | 'done' | 'failed';

export interface ResumeItem {
  review_id: string;
  status: ResumeStatus;
  weighted_score: number | null;
  pdf_minio_path: string;
  created_at: string | null;
  updated_at: string | null;
}

/** 六维度评分（agent_resume_reviews.scores）。 */
export interface DimensionScore {
  dimension: string;
  weight: number;
  score: number;
  issues: string[];
  suggestions: string[];
}

/** 逐条问题诊断（agent_resume_reviews.issues）。 */
export interface IssueItem {
  priority: string;
  dimension: string;
  description: string;
  location: string;
  suggestion: string;
}

/** 整体评价（agent_resume_reviews.summary）。 */
export interface ResumeSummary {
  highlights: string[];
  core_improvements: string[];
  overall_comment: string;
  fit_assessment: string;
}

export interface ResumeDetail {
  review_id: string;
  status: ResumeStatus;
  weighted_score: number | null;
  dimension_scores: DimensionScore[] | null;
  issues: IssueItem[] | null;
  summary: ResumeSummary | null;
  pdf_minio_path: string;
  error_msg: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ResumeListResult {
  items: ResumeItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface UploadResult {
  review_id: string;
  status: string;
  message: string;
}

/** JSON 列经 text() 取回可能是字符串，这里兜底解析为对象/数组。 */
function parseJson<T>(value: unknown): T | null {
  if (value == null) return null;
  if (typeof value === 'string') {
    try {
      return JSON.parse(value) as T;
    } catch {
      return null;
    }
  }
  return value as T;
}

type RawResumeDetail = Omit<
  ResumeDetail,
  'dimension_scores' | 'issues' | 'summary'
> & {
  dimension_scores: unknown;
  issues: unknown;
  summary: unknown;
};

export const listResumes = (params: { page?: number; page_size?: number } = {}) => {
  const qs = new URLSearchParams();
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  const s = qs.toString();
  return http.get<ResumeListResult>(`/api/v1/tenant/resume/reviews${s ? '?' + s : ''}`);
};

export const getReview = async (id: string): Promise<ResumeDetail> => {
  const raw = await http.get<RawResumeDetail>(`/api/v1/tenant/resume/reviews/${id}`);
  return {
    ...raw,
    dimension_scores: parseJson<DimensionScore[]>(raw.dimension_scores),
    issues: parseJson<IssueItem[]>(raw.issues),
    summary: parseJson<ResumeSummary>(raw.summary),
  };
};

export const deleteReview = (id: string) =>
  http.delete<{ review_id: string; deleted: boolean }>(
    `/api/v1/tenant/resume/reviews/${id}`,
  );

/** 上传简历（multipart/form-data）：后端仅使用 file 字段，仅支持 PDF。
 *  岗位/JD 参数为历史页面保留，后端会忽略。 */
export async function uploadResume(
  file: File,
  targetPosition = '',
  jobDescription = '',
): Promise<UploadResult> {
  const form = new FormData();
  form.append('file', file);
  if (targetPosition) form.append('target_position', targetPosition);
  if (jobDescription) form.append('job_description', jobDescription);

  const res = await fetch(`${API_BASE}/api/v1/tenant/resume/upload`, {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  });
  const isJson = (res.headers.get('content-type') ?? '').includes('application/json');
  const body = isJson ? ((await res.json()) as ApiEnvelope<UploadResult>) : null;
  if (!res.ok || !body || body.code !== 0) {
    throw new ApiError(
      body?.msg || `上传失败：HTTP ${res.status}`,
      body?.code ?? res.status,
      res.status,
    );
  }
  return body.data as UploadResult;
}
