-- ============================================================
-- 2026-11-14 文件域权限点收敛：qa_file:* → unified_file:*
-- 保留动作语义：page / view / upload / download
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

-- 1) 角色权限：先补 unified_file:*，再删 qa_file:*
INSERT INTO agent_role_permission (role_id, scope)
SELECT DISTINCT role_id, 'unified_file:' || split_part(scope, ':', 2)
  FROM agent_role_permission
 WHERE scope LIKE 'qa_file:%'
ON CONFLICT (role_id, scope) DO NOTHING;

DELETE FROM agent_role_permission WHERE scope LIKE 'qa_file:%';

-- 2) 菜单：文件列表入口
UPDATE agent_menu
   SET scope = 'unified_file:page'
 WHERE scope = 'qa_file:page' OR path = '/agent/qa/files';

COMMIT;

-- 3) 校验
SELECT scope, count(*) AS roles
  FROM agent_role_permission
 WHERE scope LIKE 'unified_file:%' OR scope LIKE 'qa_file:%'
 GROUP BY scope
 ORDER BY scope;
