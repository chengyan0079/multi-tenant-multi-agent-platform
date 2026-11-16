-- 模拟面试会话：简历关联、摘要、报告、得分、结束时间在会话创建时均可为空。
-- 解决创建会话必须伪造 resume_review_id / finished_at / report 的问题。
ALTER TABLE agent_platform.agent_interview_sessions
    ALTER COLUMN resume_review_id DROP NOT NULL,
    ALTER COLUMN summary DROP NOT NULL,
    ALTER COLUMN report DROP NOT NULL,
    ALTER COLUMN overall_score DROP NOT NULL,
    ALTER COLUMN finished_at DROP NOT NULL,
    ALTER COLUMN status SET DEFAULT 'in_progress';
