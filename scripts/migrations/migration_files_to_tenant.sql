-- ============================================================
-- 文件接口迁移到租户域：菜单与权限点同步（作用于已有库；幂等）
-- 变更：
--   1. 菜单「文件上传」→「文件列表」，scope 收紧为 qa_file:page（仅租户角色可见）
--   2. 非超管角色的 file:* 迁移为 qa_file:*；超管不再持有文件权限
-- 说明：接口已迁至 /api/v1/tenant/agent/files（整组 require_tenant，超管 403）
-- 用法： psql -U <用户> -h <host> -d agent_platform -f scripts/migrations/migration_files_to_tenant.sql
-- ============================================================

SET search_path TO agent_platform;

BEGIN;

UPDATE agent_menu
SET name = '文件列表', scope = 'qa_file:page'
WHERE path = '/agent/qa/files';

INSERT INTO agent_role_permission (role_id, scope)
SELECT role_id, 'qa_file:' || split_part(scope, ':', 2)
FROM agent_role_permission
WHERE scope IN ('file:page', 'file:view', 'file:upload', 'file:download')
  AND role_id <> 1
ON CONFLICT (role_id, scope) DO NOTHING;

DELETE FROM agent_role_permission WHERE scope LIKE 'file:%';

COMMIT;
