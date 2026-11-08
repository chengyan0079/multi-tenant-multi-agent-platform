-- ============================================================
-- 问答结果/会话权限点授予（作用于已有库；幂等可重复执行）
-- 仅授予 tenant_admin（租户用户）；超管不持有业务域权限点。
-- 用法： psql -U <用户> -h <host> -d <db> -f scripts/migration_qa_scope_grants.sql
-- ============================================================

SET search_path TO agent_platform;

BEGIN;

INSERT INTO agent_role_permission (role_id, scope)
SELECT r.role_id, s.scope
FROM agent_role r
CROSS JOIN (
    VALUES
        ('qa_result:page'),
        ('qa_result:view'),
        ('qa_result:review'),
        ('qa_session:page'),
        ('qa_session:add'),
        ('qa_session:delete'),
        ('qa_session:view')
) AS s(scope)
WHERE r.name = 'tenant_admin'
ON CONFLICT DO NOTHING;

COMMIT;
