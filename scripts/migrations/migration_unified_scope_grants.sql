-- ============================================================
-- 统一咨询入口权限点授予（仅用于存量库升级；全新部署已由 scripts/seed_data.sql 内置全部业务域权限）
-- 仅授予 tenant_admin（租户用户）；超管不持有业务域权限点。
-- 5 个 unified scope：unified:menu / unified:ask /
--   unified_session:page / unified_session:view / unified_session:delete
-- 接口只按 scope 校验，菜单可见性用 unified:menu。
-- 用法： psql -U <用户> -h <host> -d <db> -f scripts/migrations/migration_unified_scope_grants.sql
-- ============================================================

SET search_path TO agent_platform;

BEGIN;

INSERT INTO agent_role_permission (role_id, scope)
SELECT r.role_id, s.scope
FROM agent_role r
CROSS JOIN (
    VALUES
        ('unified:menu'),
        ('unified:ask'),
        ('unified_session:page'),
        ('unified_session:view'),
        ('unified_session:delete')
) AS s(scope)
WHERE r.name = 'tenant_admin'
ON CONFLICT DO NOTHING;

COMMIT;
