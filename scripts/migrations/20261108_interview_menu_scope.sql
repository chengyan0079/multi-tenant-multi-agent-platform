-- ============================================================
-- 面试助手菜单与权限点（作用于已有库；幂等可重复执行）
-- 变更：
--   1. /agent 下新增「面试助手」/agent/interview
--   2. 新增「面试结果」「开始面试」两个子菜单
--   3. tenant_admin 补 business:menu / interview:* 权限点
-- 用法：按项目迁移流程执行；文件内使用全限定表名，便于工具分批执行。
-- ============================================================

INSERT INTO agent_platform.agent_menu (name, path, icon, parent_id, sort_order, visible, scope)
VALUES (
    '面试助手',
    '/agent/interview',
    'CommentOutlined',
    (SELECT id FROM agent_platform.agent_menu WHERE path = '/agent'),
    4,
    true,
    'interview:menu'
)
ON CONFLICT (path) DO UPDATE SET
    name = EXCLUDED.name,
    icon = EXCLUDED.icon,
    parent_id = EXCLUDED.parent_id,
    sort_order = EXCLUDED.sort_order,
    visible = EXCLUDED.visible,
    scope = EXCLUDED.scope;

INSERT INTO agent_platform.agent_menu (name, path, icon, parent_id, sort_order, visible, scope)
VALUES
(
    '面试结果',
    '/agent/interview/results',
    'UnorderedListOutlined',
    (SELECT id FROM agent_platform.agent_menu WHERE path = '/agent/interview'),
    1,
    true,
    'interview:page'
),
(
    '开始面试',
    '/agent/interview/start',
    'FormOutlined',
    (SELECT id FROM agent_platform.agent_menu WHERE path = '/agent/interview'),
    2,
    true,
    'interview:ask'
)
ON CONFLICT (path) DO UPDATE SET
    name = EXCLUDED.name,
    icon = EXCLUDED.icon,
    parent_id = EXCLUDED.parent_id,
    sort_order = EXCLUDED.sort_order,
    visible = EXCLUDED.visible,
    scope = EXCLUDED.scope;

INSERT INTO agent_platform.agent_role_permission (role_id, scope)
SELECT r.role_id, s.scope
FROM agent_platform.agent_role r
CROSS JOIN (
    VALUES
        ('business:menu'),
        ('interview:menu'),
        ('interview:ask'),
        ('interview:page'),
        ('interview:view'),
        ('interview:delete')
) AS s(scope)
WHERE r.name = 'tenant_admin'
ON CONFLICT (role_id, scope) DO NOTHING;
