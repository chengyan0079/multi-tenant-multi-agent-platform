-- ============================================================
-- 2026-11-14 知识待补充队列：处理人/处理时间允许为空
--   pending 记录尚未被处理，resolved_user_id / resolved_at 必然为空
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

ALTER TABLE agent_knowledge_pending_queue
    ALTER COLUMN resolved_user_id DROP NOT NULL;
ALTER TABLE agent_knowledge_pending_queue
    ALTER COLUMN resolved_at DROP NOT NULL;

COMMIT;

SELECT column_name, is_nullable
  FROM information_schema.columns
 WHERE table_name = 'agent_knowledge_pending_queue'
   AND column_name IN ('resolved_user_id', 'resolved_at');
