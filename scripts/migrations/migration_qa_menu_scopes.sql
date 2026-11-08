-- ============================================================
-- 问答助手菜单 scope 对齐种子（作用于已有库；幂等）
-- 说明：/agent 树按 seed_data.sql 收紧；租户管理员补 business:menu，
--       否则 /agent 父节点会被过滤、子菜单散落为顶级。
-- 用法： psql -U <用户> -h <host> -d agent_platform -f scripts/migrations/migration_qa_menu_scopes.sql
-- ============================================================

SET search_path TO agent_platform;

BEGIN;

UPDATE agent_menu SET scope = 'business:menu' WHERE path = '/agent';
UPDATE agent_menu SET scope = 'qa:menu' WHERE path = '/agent/qa';
UPDATE agent_menu SET scope = 'qa_file:page' WHERE path = '/agent/qa/files';
UPDATE agent_menu SET scope = 'qa_result:page' WHERE path = '/agent/qa/results';
UPDATE agent_menu SET scope = 'qa:ask' WHERE path = '/agent/qa/chat';
UPDATE agent_menu SET scope = 'qa_session:page' WHERE path = '/agent/qa/sessions';

INSERT INTO agent_role_permission (role_id, scope)
SELECT 5, 'business:menu'
WHERE EXISTS (SELECT 1 FROM agent_role WHERE role_id = 5)
ON CONFLICT (role_id, scope) DO NOTHING;

COMMIT;
