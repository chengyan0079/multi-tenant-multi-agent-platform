-- ============================================================
-- 2026-11-14 agent_change_release 加 thread_id（HITL 恢复用，避免刷新丢审批上下文）
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

ALTER TABLE agent_change_release
  ADD COLUMN IF NOT EXISTS thread_id VARCHAR(128);

COMMIT;
