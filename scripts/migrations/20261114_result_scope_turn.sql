-- ============================================================
-- 2026-11-14 咨询结果域权限点：unified_result:* → unified_turn:*
-- 同时新增「咨询结果」菜单（/consultation/results）
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

-- 1) 角色权限迁移（先补后删）
INSERT INTO agent_role_permission (role_id, scope)
SELECT DISTINCT role_id, 'unified_turn:' || split_part(scope, ':', 2)
  FROM agent_role_permission
 WHERE scope LIKE 'unified_result:%'
ON CONFLICT (role_id, scope) DO NOTHING;

DELETE FROM agent_role_permission WHERE scope LIKE 'unified_result:%';

-- 2) 菜单：咨询结果
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('咨询结果', '/consultation/results', 'FileSearchOutlined',
 (SELECT id FROM agent_menu WHERE path = '/consultation'), 4, true, 'unified_turn:page')
ON CONFLICT (path) DO NOTHING;

COMMIT;

-- 3) 校验
SELECT scope, count(*) AS roles
  FROM agent_role_permission
 WHERE scope LIKE 'unified_turn:%' OR scope LIKE 'unified_result:%'
 GROUP BY scope
 ORDER BY scope;

SELECT name, path, scope FROM agent_menu WHERE path = '/consultation/results';
