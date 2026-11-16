-- ============================================================
-- 2026-11-14 菜单调整：变更评审/发布/编排 挂到「助手智能体」下
--   1) 变更评审路径统一为 /agent/db-review
--   2) 三个菜单 parent_id 指向「助手智能体」(/agent)，并重排 sort_order
-- 幂等：可重复执行；父菜单不存在时不会误更新（子查询为 NULL 会跳过）
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

-- 1) 变更评审路径统一（旧 /db_review -> /agent/db-review）
--    若已存在 /agent/db-review 则不重复改，避免唯一键冲突
UPDATE agent_menu
   SET path = '/agent/db-review'
 WHERE path = '/db_review'
   AND NOT EXISTS (SELECT 1 FROM agent_menu WHERE path = '/agent/db-review');

-- 2) 挂到「助手智能体」下并排序
UPDATE agent_menu
   SET parent_id = (SELECT id FROM agent_menu WHERE path = '/agent'),
       sort_order = 2
 WHERE path = '/agent/db-review'
   AND (SELECT id FROM agent_menu WHERE path = '/agent') IS NOT NULL;

UPDATE agent_menu
   SET parent_id = (SELECT id FROM agent_menu WHERE path = '/agent'),
       sort_order = 3
 WHERE path = '/agent/db-release'
   AND (SELECT id FROM agent_menu WHERE path = '/agent') IS NOT NULL;

UPDATE agent_menu
   SET parent_id = (SELECT id FROM agent_menu WHERE path = '/agent'),
       sort_order = 4
 WHERE path = '/agent/db-workflow'
   AND (SELECT id FROM agent_menu WHERE path = '/agent') IS NOT NULL;

-- 3) 校验输出（执行后看结果）
SELECT id, name, path, parent_id, sort_order, visible
  FROM agent_menu
 WHERE parent_id = (SELECT id FROM agent_menu WHERE path = '/agent')
 ORDER BY sort_order;

COMMIT;
