-- ============================================================
-- 菜单更名 + 智能体管理拆父子（作用于已有库；幂等可重复执行）
-- 变更：
--   1. 智能体 → 助手智能体；咨询智能体 → 问答助手；简历智能体 → 简历助手；考试智能体 → 考试助手
--   2. 智能体管理 新增子菜单「智能体列表」/agents/list
-- 用法： psql -U <用户> -h <host> -d <db> -f scripts/migration_menu_rename_agents.sql
-- ============================================================

SET search_path TO agent_platform;

BEGIN;

UPDATE agent_menu SET name = '助手智能体' WHERE path = '/agent';
UPDATE agent_menu SET name = '问答助手' WHERE path = '/agent/qa';
UPDATE agent_menu SET name = '简历助手' WHERE path = '/agent/resume';
UPDATE agent_menu SET name = '考试助手' WHERE path = '/agent/exam';

INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('智能体列表', '/agents/list', 'UnorderedListOutlined', (SELECT id FROM agent_menu WHERE path='/agents'), 1, true, 'agent:page')
ON CONFLICT (path) DO NOTHING;

COMMIT;
