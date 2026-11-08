-- ============================================================
-- 考试智能体菜单调整（作用于已有库；幂等可重复执行）
-- 变更：
--   1. 新增「开始考试」/agent/exam/start
--   2. 「考试分析」/agent/exam/analysis 改名为「考试结果」/agent/exam/results
-- 用法： psql -U <用户> -h <host> -d <db> -f scripts/migration_exam_menu.sql
-- ============================================================

SET search_path TO agent_platform;

BEGIN;

INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('开始考试', '/agent/exam/start', 'FormOutlined', (SELECT id FROM agent_menu WHERE path='/agent/exam'), 1, true, NULL)
ON CONFLICT (path) DO NOTHING;

UPDATE agent_menu
SET name = '考试结果', path = '/agent/exam/results', icon = 'ProfileOutlined', sort_order = 2
WHERE path = '/agent/exam/analysis';

COMMIT;
