-- ============================================================
-- 智能体业务域菜单迁移（作用于已有库，不重建；幂等可重复执行）
-- 变更：
--   1. 删除旧菜单：会话运行 / 咨询问答 / 文件管理 / 文件列表
--   2. 新增「智能体」业务域菜单树（咨询 / 简历 / 考试），整树 scope=NULL（开发期登录可见）
-- 说明：schema.sql 的 SEED_MENU 已同步为最终形态；本脚本用于存量库增量升级。
-- 用法： psql -U <用户> -h <host> -d <db> -f scripts/migration_agent_menu.sql
-- ============================================================

SET search_path TO agent_platform;

BEGIN;

-- 唯一索引兜底（已存在则忽略，保证 ON CONFLICT (path) 可用）
CREATE UNIQUE INDEX IF NOT EXISTS uk_menu_path ON agent_menu (path);

-- 1) 删除旧菜单（子节点一并删除，避免遗留孤儿）
DELETE FROM agent_menu WHERE path IN ('/files/list', '/files', '/qa', '/sessions');

-- 2) 智能体（业务域）根节点
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('智能体', '/agent', 'AppstoreOutlined', 0, 2, true, NULL)
ON CONFLICT (path) DO NOTHING;

-- 3) 一级子菜单：咨询 / 简历 / 考试
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('咨询智能体', '/agent/qa', 'CommentOutlined', (SELECT id FROM agent_menu WHERE path='/agent'), 1, true, NULL),
('简历智能体', '/agent/resume', 'ProfileOutlined', (SELECT id FROM agent_menu WHERE path='/agent'), 2, true, NULL),
('考试智能体', '/agent/exam', 'FileTextOutlined', (SELECT id FROM agent_menu WHERE path='/agent'), 3, true, NULL)
ON CONFLICT (path) DO NOTHING;

-- 4) 咨询智能体二级菜单
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('文件上传', '/agent/qa/files', 'UploadOutlined', (SELECT id FROM agent_menu WHERE path='/agent/qa'), 1, true, NULL),
('问答结果', '/agent/qa/results', 'UnorderedListOutlined', (SELECT id FROM agent_menu WHERE path='/agent/qa'), 2, true, NULL),
('QA问答', '/agent/qa/chat', 'CommentOutlined', (SELECT id FROM agent_menu WHERE path='/agent/qa'), 3, true, NULL),
('会话列表', '/agent/qa/sessions', 'MessageOutlined', (SELECT id FROM agent_menu WHERE path='/agent/qa'), 4, true, NULL)
ON CONFLICT (path) DO NOTHING;

-- 5) 简历智能体二级菜单
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('简历分析', '/agent/resume/analysis', 'ProfileOutlined', (SELECT id FROM agent_menu WHERE path='/agent/resume'), 1, true, NULL)
ON CONFLICT (path) DO NOTHING;

-- 6) 考试智能体二级菜单
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('考试分析', '/agent/exam/analysis', 'FormOutlined', (SELECT id FROM agent_menu WHERE path='/agent/exam'), 1, true, NULL)
ON CONFLICT (path) DO NOTHING;

COMMIT;
