-- ============================================================
-- RBAC 默认播种（幂等，可重复执行）
-- 对应 backend/core/rbac.py 的 DEFAULT_ROLE_SCOPES
-- 作用：建好三个内置角色 student/teacher/admin 及其权限点，并分配开发用户，
--       使 RbacService.resolve() 能从库命中（而非 DEV_ROLE 兜底）。
-- ============================================================

-- 1) 角色目录（全局）
INSERT INTO agent_role (role_id, name, description, created_at) VALUES
  ('student', 'student', '内置角色 student（问答/面试/本人简历）', now()),
  ('teacher', 'teacher', '内置角色 teacher（+批改/HITL/本班）', now()),
  ('admin',   'admin',   '内置角色 admin（全部权限）',           now())
ON CONFLICT (role_id) DO NOTHING;


-- 2) 角色 → 权限点
-- student
INSERT INTO agent_role_permission (role_id, scope) VALUES
  ('student', 'qa:chat'),
  ('student', 'interview:run'),
  ('student', 'resume:review:self'),
  ('student', 'trace:view:self')
ON CONFLICT (role_id, scope) DO NOTHING;
-- teacher
INSERT INTO agent_role_permission (role_id, scope) VALUES
  ('teacher', 'qa:chat'),
  ('teacher', 'interview:run'),
  ('teacher', 'resume:review:self'),
  ('teacher', 'resume:review:any'),
  ('teacher', 'exam:grade'),
  ('teacher', 'hitl:approve'),
  ('teacher', 'class:view')
ON CONFLICT (role_id, scope) DO NOTHING;
-- admin（* = 全部）
INSERT INTO agent_role_permission (role_id, scope) VALUES
  ('admin', '*')
ON CONFLICT (role_id, scope) DO NOTHING;


-- 3) 开发用户分配（让 resolve() 从库命中）
--    ⚠️ 将下面的 dev-user / dev-tenant 替换为你 .env 的 DEV_USER_ID / DEV_TENANT_ID
--    改角色可验证不同角色的效果（student/teacher/admin）
INSERT INTO agent_user_tenant (user_id, tenant_id, role_id, created_at) VALUES
  ('dev-user', 'dev-tenant', 'admin', now())
ON CONFLICT (user_id, tenant_id) DO NOTHING;


-- 4) 校验：列出角色及其权限点
SELECT r.role_id,
       r.name,
       (SELECT string_agg(p.scope, ', ' ORDER BY p.scope)
          FROM agent_role_permission p WHERE p.role_id = r.role_id) AS scopes
FROM agent_role r
ORDER BY r.role_id;

-- 校验：列出用户-租户-角色分配
SELECT user_id, tenant_id, role_id FROM agent_user_tenant ORDER BY tenant_id, user_id;
