-- ============================================================
-- agent-platform 种子数据（平台基础 + 2 个内置角色）
-- 依据当前数据库导出，仅含：
--   · 平台超管租户（agent_tenant id=0）
--   · 超管账号 admin（agent_user + agent_user_tenant）
--   · 2 个内置角色：admin(role_id=1)、tenant_admin(role_id=5)
--   · 角色权限点（agent_role_permission）
--   · 菜单（agent_menu）
--   · Agent 目录（agent）
--   · 模型注册表（agent_model_registry，含当前环境 api_key）
-- 权限域划分（以 backend/security/rbac.py 的 Business / Agent / System 为准）：
--   · 超管 admin：基建域 + 平台域 64 个，不含任何业务域权限
--   · 租户管理员 tenant_admin：业务域 36 个 + 租户自管平台域 30 个（user/role/message/rbac
--     /config/audit/dashboard），不含 agent/model/tool/menu/tenant 等平台级管理权限
-- 不含其他租户、账号、角色（student/teacher 等由超管在前端创建）。
-- 执行： psql -U <用户> -h <host> -d agent_platform -f scripts/seed_data.sql
-- 幂等：全部 ON CONFLICT DO NOTHING，可重复执行。
-- 注意：模型 api_key 为当前环境配置，请勿外泄或提交到公开仓库。
-- ============================================================

SET search_path TO unified_schemas;

-- ------------------------------------------------------------
-- 1) 平台超管租户（id=0）
-- ------------------------------------------------------------
INSERT INTO agent_tenant (id, name, enabled) VALUES
(0, '平台超管租户', true)
ON CONFLICT (id) DO NOTHING;

-- ------------------------------------------------------------
-- 2) 超管账号（密码 123456，仅本地开发）
-- ------------------------------------------------------------
INSERT INTO "agent_user" (username, name, password, tenant_id, is_super_admin) VALUES
('admin', 'admin', '123456', 0, true)
ON CONFLICT (username) DO NOTHING;

-- ------------------------------------------------------------
-- 3) 2 个内置角色（业务键 role_id=1 超管 / role_id=5 租户管理员）
--    tenant_admin 必须预置：admin/tenant.py 建租户时要按 name 取该角色，缺则建租户失败。
-- ------------------------------------------------------------
INSERT INTO agent_role (role_id, name, description, create_user_id, update_user_id) VALUES
(1, 'admin', '平台超管（全局唯一，以 agent_user.is_super_admin 为准）',
 (SELECT id FROM "agent_user" WHERE username='admin'),
 (SELECT id FROM "agent_user" WHERE username='admin')),
(5, 'tenant_admin', '租户管理员（业务域 + 租户自管平台域）',
 (SELECT id FROM "agent_user" WHERE username='admin'),
 (SELECT id FROM "agent_user" WHERE username='admin'))
ON CONFLICT (role_id) DO NOTHING;

-- ------------------------------------------------------------
-- 4) 超管权限点（64 个：基建域 + 平台域，不含任何业务域）
-- ------------------------------------------------------------
INSERT INTO agent_role_permission (role_id, scope) VALUES
(1, 'agent:add'),
(1, 'agent:delete'),
(1, 'agent:list'),
(1, 'agent:menu'),
(1, 'agent:page'),
(1, 'agent:status'),
(1, 'agent:update'),
(1, 'agent:view'),
(1, 'audit:menu'),
(1, 'audit:page'),
(1, 'audit:view'),
(1, 'config:add'),
(1, 'config:delete'),
(1, 'config:execute'),
(1, 'config:menu'),
(1, 'config:page'),
(1, 'config:rollback'),
(1, 'config:update'),
(1, 'config:view'),
(1, 'dashboard:menu'),
(1, 'dashboard:view'),
(1, 'menu:add'),
(1, 'menu:delete'),
(1, 'menu:menu'),
(1, 'menu:page'),
(1, 'menu:status'),
(1, 'menu:update'),
(1, 'message:menu'),
(1, 'message:page'),
(1, 'message:status'),
(1, 'message:view'),
(1, 'model:add'),
(1, 'model:delete'),
(1, 'model:menu'),
(1, 'model:page'),
(1, 'model:status'),
(1, 'model:update'),
(1, 'model:view'),
(1, 'rbac:menu'),
(1, 'role:add'),
(1, 'role:delete'),
(1, 'role:menu'),
(1, 'role:page'),
(1, 'role:update'),
(1, 'tenant:add'),
(1, 'tenant:delete'),
(1, 'tenant:menu'),
(1, 'tenant:page'),
(1, 'tenant:status'),
(1, 'tenant:view'),
(1, 'tool:add'),
(1, 'tool:delete'),
(1, 'tool:menu'),
(1, 'tool:page'),
(1, 'tool:status'),
(1, 'tool:update'),
(1, 'tool:view'),
(1, 'db_connection:add'),
(1, 'db_connection:delete'),
(1, 'db_connection:page'),
(1, 'db_connection:status'),
(1, 'db_connection:update'),
(1, 'db_connection:view'),
(1, 'user:add'),
(1, 'user:delete'),
(1, 'user:menu'),
(1, 'user:page'),
(1, 'user:status'),
(1, 'user:update'),
(1, 'user:view')
ON CONFLICT (role_id, scope) DO NOTHING;

-- ------------------------------------------------------------
-- 4.1) 租户管理员权限点（47 个：业务域 17 + 租户自管平台域 30）
--      不含 agent/model/tool/menu/tenant 等平台级管理权限（仅超管）。
-- ------------------------------------------------------------
INSERT INTO agent_role_permission (role_id, scope) VALUES
-- 业务域分组菜单 / 统一咨询入口 / 会话管理
(5, 'business:menu'),
(5, 'unified:menu'),
(5, 'unified:ask'),
(5, 'unified_session:page'),
(5, 'unified_session:view'),
(5, 'unified_session:delete'),
-- 问答文件（知识库文档上传/下载）
(5, 'unified_file:page'),
(5, 'unified_file:view'),
(5, 'unified_file:upload'),
(5, 'unified_file:download'),
-- 统一问答结果（原 qa_result；数据源已是 agent_unified_turn）
(5, 'unified_turn:page'),
(5, 'unified_turn:view'),
(5, 'unified_turn:review'),
-- 租户自管平台域：用户 / 角色 / 消息 / 权限中心入口
(5, 'user:menu'),
(5, 'user:page'),
(5, 'user:view'),
(5, 'user:add'),
(5, 'user:update'),
(5, 'user:delete'),
(5, 'user:status'),
(5, 'role:menu'),
(5, 'role:page'),
(5, 'role:add'),
(5, 'role:update'),
(5, 'role:delete'),
(5, 'message:menu'),
(5, 'message:page'),
(5, 'message:view'),
(5, 'message:status'),
(5, 'rbac:menu'),
-- 配置中心 / 审计 / 仪表盘
(5, 'config:menu'),
(5, 'config:page'),
(5, 'config:view'),
(5, 'config:add'),
(5, 'config:update'),
(5, 'config:execute'),
(5, 'config:delete'),
(5, 'config:rollback'),
(5, 'audit:menu'),
(5, 'audit:page'),
(5, 'audit:view'),
(5, 'dashboard:menu'),
(5, 'dashboard:view')
ON CONFLICT (role_id, scope) DO NOTHING;

-- ------------------------------------------------------------
-- 5) 超管租户绑定（user_id, tenant_id, role_id）
-- ------------------------------------------------------------
INSERT INTO agent_user_tenant (user_id, tenant_id, role_id, created_at) VALUES
((SELECT id FROM "agent_user" WHERE username='admin'), 0, 1, date_trunc('second', now()))
ON CONFLICT (user_id, tenant_id) DO NOTHING;

-- ------------------------------------------------------------
-- 6) 菜单（按 path 幂等；父节点先插入）
-- ------------------------------------------------------------
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('监控概览', '/dashboard', 'DashboardOutlined', 0, 1, true, 'dashboard:menu'),
('助手智能体', '/agent', 'AppstoreOutlined', 0, 2, true, 'business:menu'),
('智能体管理', '/agents', 'RobotOutlined', 0, 3, true, 'agent:menu'),
('工具与插件', '/tools', 'ToolOutlined', 0, 4, true, 'tool:menu'),
('模型配置', '/models', 'DeploymentUnitOutlined', 0, 5, true, 'model:menu'),
('配置中心', '/config', 'SettingOutlined', 0, 6, true, 'config:menu'),
('审计日志', '/audit', 'FileSearchOutlined', 0, 7, true, 'audit:menu'),
('权限中心', '/rbac', 'SafetyCertificateOutlined', 0, 8, true, 'rbac:menu'),
('消息管理', '/messages', 'MailOutlined', 0, 10, true, 'message:menu'),
('统一咨询', '/consultation', 'CommentOutlined', 0, 9, true, 'unified:menu')
ON CONFLICT (path) DO NOTHING;

-- 工具与插件：工具管理 / 数据库管理列表
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('工具管理', '/tools/agent-tools', 'ToolOutlined', (SELECT id FROM agent_menu WHERE path='/tools'), 1, true, 'tool:page'),
('数据库管理列表', '/tools/db-connections', 'DatabaseOutlined', (SELECT id FROM agent_menu WHERE path='/tools'), 2, true, 'db_connection:page')
ON CONFLICT (path) DO NOTHING;

-- 统一咨询：父节点先单独提交，子菜单子查询才能取到其 id
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('业务咨询', '/consultation/chat', 'CommentOutlined', (SELECT id FROM agent_menu WHERE path='/consultation'), 1, true, 'unified:ask'),
('会话管理', '/consultation/sessions', 'UnorderedListOutlined', (SELECT id FROM agent_menu WHERE path='/consultation'), 2, true, 'unified_session:page')
ON CONFLICT (path) DO NOTHING;

-- 智能体管理：智能体列表
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('智能体列表', '/agents/list', 'UnorderedListOutlined', (SELECT id FROM agent_menu WHERE path='/agents'), 1, true, 'agent:page')
ON CONFLICT (path) DO NOTHING;

-- 助手智能体：问答
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('问答助手', '/agent/qa', 'CommentOutlined', (SELECT id FROM agent_menu WHERE path='/agent'), 1, true, 'unified:ask')
ON CONFLICT (path) DO NOTHING;

-- 问答助手：文件上传 / 问答结果（发起入口 QA问答/会话列表 已由统一咨询收口，菜单移除）
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('文件列表', '/agent/qa/files', 'UploadOutlined', (SELECT id FROM agent_menu WHERE path='/agent/qa'), 1, true, 'unified_file:page'),
('问答结果', '/agent/qa/results', 'UnorderedListOutlined', (SELECT id FROM agent_menu WHERE path='/agent/qa'), 2, true, 'qa_result:page')
ON CONFLICT (path) DO NOTHING;

-- 审计日志：业务审计 / 登录日志 / 调用日志
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('业务审计', '/audit/operation', 'FileTextOutlined', (SELECT id FROM agent_menu WHERE path='/audit'), 1, true, 'audit:page'),
('登录日志', '/audit/login', 'LoginOutlined', (SELECT id FROM agent_menu WHERE path='/audit'), 2, true, 'audit:page'),
('调用日志', '/audit/api', 'ApiOutlined', (SELECT id FROM agent_menu WHERE path='/audit'), 3, true, 'audit:page')
ON CONFLICT (path) DO NOTHING;

-- 配置中心：配置列表 / 配置审核 / 审核记录
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('配置列表', '/config/request', 'FormOutlined', (SELECT id FROM agent_menu WHERE path='/config'), 1, true, 'config:page'),
('配置审核', '/config/review', 'AuditOutlined', (SELECT id FROM agent_menu WHERE path='/config'), 2, true, 'config:page'),
('审核记录', '/config/review-log', 'AuditOutlined', (SELECT id FROM agent_menu WHERE path='/config'), 3, true, 'config:page')
ON CONFLICT (path) DO NOTHING;

-- 权限中心：租户管理 / 用户管理 / 角色管理 / 菜单管理
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('租户管理', '/tenants', 'TeamOutlined', (SELECT id FROM agent_menu WHERE path='/rbac'), 1, true, 'tenant:menu'),
('用户管理', '/users', 'UserOutlined', (SELECT id FROM agent_menu WHERE path='/rbac'), 2, true, 'user:menu'),
('角色管理', '/roles', 'KeyOutlined', (SELECT id FROM agent_menu WHERE path='/rbac'), 3, true, 'role:menu'),
('菜单管理', '/menus', 'MenuOutlined', (SELECT id FROM agent_menu WHERE path='/rbac'), 4, true, 'menu:menu')
ON CONFLICT (path) DO NOTHING;

-- 消息管理：消息队列 / 死信队列
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('消息队列', '/messages/queue', 'SendOutlined', (SELECT id FROM agent_menu WHERE path='/messages'), 1, true, 'message:page'),
('死信队列', '/messages/dead-letters', 'ExceptionOutlined', (SELECT id FROM agent_menu WHERE path='/messages'), 2, true, 'message:page')
ON CONFLICT (path) DO NOTHING;

-- ------------------------------------------------------------
-- 7) Agent 目录（agent_type 与代码 AgentRegistry 一致）
-- ------------------------------------------------------------
INSERT INTO agent (
    tenant_id, agent_type, name, description, input_schema, enabled,
    version, create_user_id, update_user_id) VALUES
(0, 'qa', '问答助手', '智能问答与多轮对话', NULL, true,
    '1.0.0', (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin'))
ON CONFLICT (tenant_id, agent_type) DO NOTHING;

-- ------------------------------------------------------------
-- 8) 模型注册表（按当前库真实值；api_key 为当前环境配置）
-- ------------------------------------------------------------
INSERT INTO agent_model_registry (
    model_type, name, provider, base_url, api_key, endpoint_path,
    temperature, timeout_s, max_retries, enabled, sort_order, description,
    create_user_id, update_user_id) VALUES
('llm', 'deepseek/deepseek-flash', 'openai', 'https://tokenhub.tencentmaas.com/plan/v3',
    'sk-tp-BsnoIOov68JV8zesz4YF6xPQreDKOxRHzgVS1ySZUWld8f8d', NULL,
    0.2, 60, 2, true, 1, '默认 LLM（deepseek/deepseek-flash，经 OpenAI 兼容网关）',
    (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin')),
('embedding', 'bge-m3', 'local', NULL, NULL, 'models/BAAI/bge-m3',
    NULL, NULL, NULL, true, 1, 'BGE-M3 向量化（本地 FlagEmbedding）',
    (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin')),
('reranker', 'bge-reranker-v2-m3', 'local', NULL, NULL, 'models/BAAI/bge-reranker-v2-m3',
    NULL, NULL, NULL, true, 1, 'BGE-Reranker-v2-m3 精排（本地）',
    (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin')),
('classifier', 'intent_classifier', 'local', NULL, NULL, 'models/classifier/intent_classifier',
    NULL, NULL, NULL, true, 1, '中文意图分类（离线训练产物）',
    (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin'))
ON CONFLICT (model_type, name) DO NOTHING;

-- ------------------------------------------------------------
-- 工具目录种子（web_search / code_exec）
-- config 存运行期凭据（api_key / endpoint / provider 等），由运营在 agent_tool 表维护；默认空 {} 走降级。
-- ------------------------------------------------------------
INSERT INTO agent_tool (id, tenant_id, name, plugin, description, "schema", config, enabled) VALUES
('11111111-1111-1111-1111-111111111111', 0, 'web_search', 'web_search', '联网检索兜底', '{}', '{}', true),
('22222222-2222-2222-2222-222222222222', 0, 'code_exec', 'code_exec', '代码沙箱执行', '{}', '{}', true)
ON CONFLICT (tenant_id, name) DO NOTHING;


-- ------------------------------------------------------------
-- db_review Agent 目录（租户 0）
-- ------------------------------------------------------------
INSERT INTO agent (tenant_id, agent_type, name, description, input_schema, enabled, version,
    create_user_id, update_user_id)
VALUES (0, 'db_review', '变更评审', '数据库变更评审（元数据预检/慢SQL/风险分级/审批）', NULL, true, '1.0.0',
    (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin'))
ON CONFLICT (tenant_id, agent_type) DO NOTHING;


-- 变更评审（db_review）菜单
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('变更评审', '/agent/db-review', 'DatabaseOutlined', (SELECT id FROM agent_menu WHERE path='/agent'), 2, true, 'unified:ask')
ON CONFLICT (path) DO NOTHING;


-- 统一咨询：图状态列表
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('图状态列表', '/consultation/graph-states', 'PartitionOutlined', (SELECT id FROM agent_menu WHERE path='/consultation'), 3, true, 'unified_session:page')
ON CONFLICT (path) DO NOTHING;

-- 咨询结果（agent_unified_turn：详情 / 质量测评）
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('咨询结果', '/consultation/results', 'FileSearchOutlined', (SELECT id FROM agent_menu WHERE path='/consultation'), 4, true, 'unified_turn:page')
ON CONFLICT (path) DO NOTHING;


-- ------------------------------------------------------------
-- db_release Agent 目录（租户 0）
-- ------------------------------------------------------------
INSERT INTO agent (tenant_id, agent_type, name, description, input_schema, enabled, version,
    create_user_id, update_user_id)
VALUES (0, 'db_release', '变更发布', '沙箱验证已审批变更并输出原样 SQL（不执行生产）', NULL, true, '1.0.0',
    (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin'))
ON CONFLICT (tenant_id, agent_type) DO NOTHING;

-- 变更发布（db_release）菜单
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('变更发布', '/agent/db-release', 'RocketOutlined', (SELECT id FROM agent_menu WHERE path='/agent'), 3, true, 'unified:ask')
ON CONFLICT (path) DO NOTHING;


-- 统一业务编排（变更治理）
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('变更编排', '/agent/db-workflow', 'ApartmentOutlined', (SELECT id FROM agent_menu WHERE path='/agent'), 4, true, 'unified:ask')
ON CONFLICT (path) DO NOTHING;


-- 内置工具（租户 0）：与 mcp/builtin 代码实现一一对应
INSERT INTO agent_tool (id, tenant_id, name, plugin, description, "schema", config, enabled) VALUES
('33333333-3333-3333-3333-333333333333', 0, 'db_metadata', 'db_metadata', '数据库元数据（DDL/索引/统计）', '{}', '{}', true),
('44444444-4444-4444-4444-444444444444', 0, 'slow_sql_explain', 'slow_sql_explain', '慢SQL分析（纯规则，不连库）', '{}', '{}', true),
('55555555-5555-5555-5555-555555555555', 0, 'sql_dialect_validate', 'sql_dialect_validate', 'SQL 方言/后缀校验', '{}', '{}', true),
('66666666-6666-6666-6666-666666666666', 0, 'sql_exec_sandbox', 'sql_exec_sandbox', '沙箱执行已审批SQL', '{}', '{}', true)
ON CONFLICT (tenant_id, name) DO NOTHING;
