import { http } from './http';

export interface ExamSubmissionItem {
  submission_id: string;
  exam_id: string;
  exam_title: string;
  status: string;
  submitted_at: string | null;
}

export interface ExamReviewQuestion {
  question_id: string;
  question_no: number;
  question_type: string;
  knowledge_tag?: string;
  content?: string;
  student_answer: string;
  correct_answer: string;
  ai_feedback: string;
  teacher_comment: string;
  needs_review: boolean;
  score: number;
  full_score: number;
  final_score: number;
}

export interface ExamPreReviewSummary {
  total_score: number;
  full_score: number;
  score_rate: number;
  needs_review_count?: number;
  by_question: ExamReviewQuestion[];
}

export interface ExamWeakPoint {
  tag: string;
  wrong_count: number;
  total_count: number;
  question_nos?: number[];
}

export interface ExamSubmissionDetail {
  submission_id: string;
  status: string;
  pre_review_summary?: ExamPreReviewSummary;
  weak_points?: (string | ExamWeakPoint)[];
  weak_points_summary?: string;
}

export interface ExamPendingReviewItem {
  submission_id: string;
  student_name: string;
  exam_title: string;
  submitted_at: string | null;
  pre_review: { total_score: number; full_score: number; needs_review_count: number };
  weak_points: ExamWeakPoint[];
}

export interface ExamReviewDetail {
  submission_id: string;
  student_id: string;
  pre_review_summary?: ExamPreReviewSummary;
  weak_points?: (string | ExamWeakPoint)[];
  weak_points_summary?: string;
}

/* ---------- 学生侧 ---------- */

/** 当前用户最近的考试提交列表（最多 20 条）。 */
export async function listMyExamSubmissions() {
  return http.get<{ items: ExamSubmissionItem[] }>('/api/v1/tenant/exam/my-submissions');
}

/** 获取本人考试提交详情；未发布时仅返回状态。 */
export async function getMyExamSubmission(submissionId: string) {
  return http.get<ExamSubmissionDetail>(`/api/v1/tenant/exam/my-submissions/${submissionId}`);
}

/* ---------- 教师侧 ---------- */

/** 教师待复核列表（本租户 pending_review 提交）。 */
export async function listPendingExamReviews() {
  return http.get<{ items: ExamPendingReviewItem[]; total: number }>(
    '/api/v1/tenant/exam/pending-reviews',
  );
}

/** 教师复核快照：预评摘要与薄弱点。 */
export async function getExamSubmissionReview(submissionId: string) {
  return http.get<ExamReviewDetail>(`/api/v1/tenant/exam/submissions/${submissionId}/review`);
}

/** 教师确认/修改并发布。 */
export async function confirmExamReview(
  submissionId: string,
  action: 'approve' | 'modify',
  modifications: { question_id: string; new_score?: number; comment?: string }[] = [],
) {
  return http.post<{ submission_id: string; status: string; final_score?: number }>(
    `/api/v1/tenant/exam/submissions/${submissionId}/confirm`,
    { action, modifications },
  );
}
