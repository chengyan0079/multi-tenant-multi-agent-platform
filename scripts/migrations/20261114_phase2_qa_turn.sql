-- ============================================================
-- 2026-11-14 阶段2：问答结果并入 agent_unified_turn
--   1) agent_qa_ragas_evals：qa_result_id -> turn_id，加 reference_answer / retrieved_contexts
--   2) 回填 turn_id（按 trace_id + tenant + user 匹配 turn）
--   3) 删除 agent_qa_results
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

-- 1) 评测表：外键改挂 turn，并带上标准答案与上下文快照
ALTER TABLE agent_qa_ragas_evals RENAME COLUMN qa_result_id TO turn_id;
ALTER TABLE agent_qa_ragas_evals
  ADD COLUMN IF NOT EXISTS reference_answer TEXT,
  ADD COLUMN IF NOT EXISTS retrieved_contexts JSONB;
DROP INDEX IF EXISTS idx_qa_ragas_qa_result;
CREATE INDEX IF NOT EXISTS idx_qa_ragas_turn ON agent_qa_ragas_evals (turn_id);

-- 2) 历史回填：qa_results.id 曾被 evals 引用；若仍能从 trace 对到 turn 则修正
UPDATE agent_qa_ragas_evals e
   SET turn_id = t.id
  FROM agent_unified_turn t
 WHERE e.turn_id IS NOT NULL
   AND t.trace_id = e.trace_id
   AND t.tenant_id = e.tenant_id
   AND t.agent_type = 'qa';

-- 3) 删除重复表（问答历史以 agent_unified_turn 为唯一源）
DROP TABLE IF EXISTS agent_qa_results;

COMMIT;
