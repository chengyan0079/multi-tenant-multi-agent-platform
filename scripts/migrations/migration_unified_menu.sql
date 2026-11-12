-- ============================================================
-- 统一咨询菜单（仅用于存量库升级；全新部署已由 scripts/seed_data.sql 内置，无需执行本文件）
-- 父节点「统一咨询」/consultation（与「助手智能体」/agent 同级，top-level parent_id=0），
-- 下挂：
--   业务咨询  /consultation/chat       (scope unified:ask)
--   会话管理  /consultation/sessions   (scope unified_session:page)
-- 前端路由由 RequireScope 守卫，无对应 scope 时点击被拦回 /dashboard。
-- 用法： psql -U <用户> -h <host> -d <db> -f scripts/migrations/migration_unified_menu.sql
-- ============================================================

SET search_path TO agent_platform;

BEGIN;

-- 父节点（与 /agent 同级）
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('统一咨询', '/consultation', 'CommentOutlined', 0, 9, true, 'unified:menu')
ON CONFLICT (path) DO NOTHING;

-- 子菜单：业务咨询
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('业务咨询', '/consultation/chat', 'CommentOutlined',
 (SELECT id FROM agent_menu WHERE path = '/consultation'), 1, true, 'unified:ask')
ON CONFLICT (path) DO NOTHING;

-- 子菜单：会话管理
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('会话管理', '/consultation/sessions', 'UnorderedListOutlined',
 (SELECT id FROM agent_menu WHERE path = '/consultation'), 2, true, 'unified_session:page')
ON CONFLICT (path) DO NOTHING;

COMMIT;
