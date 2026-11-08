-- ============================================================
-- 下线冗余表 + 会话标题（作用于已有库；幂等可重复执行）
-- 变更：
--   1. agent_thread 新增 title（默认「新会话」）
--   2. 删除 agent_qa_sessions（摘要由 checkpointer 承载）
--   3. 删除 agent_escalation（不做人工接入）
--   4. 删除 agent_message（消息由 checkpointer 承载）
-- 用法： psql -U <用户> -h <host> -d agent_platform -f scripts/migrations/migration_drop_redundant_tables.sql
-- ============================================================

SET search_path TO agent_platform;

BEGIN;

ALTER TABLE agent_thread
    ADD COLUMN IF NOT EXISTS title VARCHAR(255) NOT NULL DEFAULT '新会话';

UPDATE agent_thread SET title = '新会话' WHERE title IS NULL OR title = '';

DROP TABLE IF EXISTS agent_qa_sessions;
DROP TABLE IF EXISTS agent_escalation;
DROP TABLE IF EXISTS agent_message;

COMMIT;
