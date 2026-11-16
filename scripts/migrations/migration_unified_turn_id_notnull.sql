-- ============================================================
-- 业务表 turn_id 收紧 NOT NULL（Step 1 迁移加列时留可空，待统一层回填后收紧）
-- 旧业务数据已在 Step 1 清空；若存在残留 NULL 行，本迁移会失败（fail-fast，需先排查再收紧）。
-- 用法： psql -U <用户> -h <host> -d <db> -f scripts/migrations/migration_unified_turn_id_notnull.sql
-- ============================================================

SET search_path TO agent_platform;

BEGIN;

ALTER TABLE agent_qa_results ALTER COLUMN turn_id SET NOT NULL;
ALTER TABLE agent_interview_sessions ALTER COLUMN turn_id SET NOT NULL;
ALTER TABLE agent_exam_submissions ALTER COLUMN turn_id SET NOT NULL;
ALTER TABLE agent_resume_reviews ALTER COLUMN turn_id SET NOT NULL;

COMMIT;
