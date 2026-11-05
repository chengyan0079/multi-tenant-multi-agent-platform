/** 简历评审接口（后端 /api/v1/tenant/resume；按租户 + 用户隔离，超管无权限）。 */

import { API_BASE, ApiError, authHeaders, http, type ApiEnvelope } from './http';

export type ResumeStatus = 'processing' | 'completed' | 'failed';

export interface ResumeItem {
  review_id: string;
  status: ResumeStatus;
  weighted_score: number | null;
  pdf_minio_path: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface ResumeDetail {
  review_id: string;
  status: ResumeStatus;
  weighted_score: number | null;
  dimension_scores: Record<string, number> | null;
  issues: string[] | null;
  summary: string | null;
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

export const listResumes = (params: { page?: number; page_size?: number } = {}) => {
  const qs = new URLSearchParams();
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  const s = qs.toString();
  return http.get<ResumeListResult>(`/api/v1/tenant/resume/reviews${s ? '?' + s : ''}`);
};

export const getReview = (id: string) =>
  http.get<ResumeDetail>(`/api/v1/tenant/resume/reviews/${id}`);

export const deleteReview = (id: string) =>
  http.delete<{ review_id: string; deleted: boolean }>(`/api/v1/tenant/resume/reviews/${id}`);

/** 上传简历（multipart/form-data）：不能走 JSON 封装，需 FormData + 自动 boundary。 */
export async function uploadResume(
  file: File,
  targetPosition = '',
  jobDescription = '',
): Promise<UploadResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('target_position', targetPosition);
  form.append('job_description', jobDescription);

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
