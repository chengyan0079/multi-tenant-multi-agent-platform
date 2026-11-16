-- ============================================================
-- 2026-11-13 agent_file 扩展：Agent 业务归属字段（db_review 等）
-- 可空列，兼容现有通用文件上传；执行前请备份。
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

ALTER TABLE agent_file ADD COLUMN IF NOT EXISTS agent_type VARCHAR(64);
ALTER TABLE agent_file ADD COLUMN IF NOT EXISTS file_kind VARCHAR(16);
ALTER TABLE agent_file ADD COLUMN IF NOT EXISTS thread_id VARCHAR(64);
ALTER TABLE agent_file ADD COLUMN IF NOT EXISTS request_id VARCHAR(64);
ALTER TABLE agent_file ADD COLUMN IF NOT EXISTS db_type VARCHAR(16);

CREATE INDEX IF NOT EXISTS idx_agent_file_thread ON agent_file (thread_id);
CREATE INDEX IF NOT EXISTS idx_agent_file_request ON agent_file (request_id);

COMMENT ON COLUMN agent_file.agent_type IS '归属 Agent 类型（如 db_review）';
COMMENT ON COLUMN agent_file.file_kind IS '文件用途：script 脚本 / drill 回滚演练 / attachment 附件';
COMMENT ON COLUMN agent_file.thread_id IS '关联会话/线程ID';
COMMENT ON COLUMN agent_file.request_id IS '关联变更单ID';
COMMENT ON COLUMN agent_file.db_type IS '目标库类型（mysql/postgresql），用于脚本方言校验';

COMMIT;
