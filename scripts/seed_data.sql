-- ============================================================
-- agent-platform 种子数据（平台基础 + 超管）
-- 依据当前数据库导出，仅含：
--   · 平台超管租户（agent_tenant id=0）
--   · 超管账号 admin（agent_user + agent_user_tenant）
--   · 超管角色 admin 及其 67 个权限点（agent_role / agent_role_permission）
--   · 菜单（agent_menu）
--   · Agent 目录（agent）
--   · 模型注册表（agent_model_registry，含当前环境 api_key）
-- 不含其他租户、账号、角色（tenant_admin/student/teacher 等由超管在前端创建）。
-- 执行： psql -U <用户> -h <host> -d agent_platform -f scripts/seed_data.sql
-- 幂等：全部 ON CONFLICT DO NOTHING，可重复执行。
-- 注意：模型 api_key 为当前环境配置，请勿外泄或提交到公开仓库。
-- ============================================================

SET search_path TO agent_platform;

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
-- 3) 超管角色（业务键 role_id=1）
-- ------------------------------------------------------------
INSERT INTO agent_role (role_id, name, description, create_user_id, update_user_id) VALUES
(1, 'admin', '平台超管（全局唯一，以 agent_user.is_super_admin 为准）',
 (SELECT id FROM "agent_user" WHERE username='admin'),
 (SELECT id FROM "agent_user" WHERE username='admin'))
ON CONFLICT (role_id) DO NOTHING;

-- ------------------------------------------------------------
-- 4) 超管权限点（67 个，与当前库一致）
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
(1, 'tenant:update'),
(1, 'tenant:view'),
(1, 'tool:add'),
(1, 'tool:delete'),
(1, 'tool:menu'),
(1, 'tool:page'),
(1, 'tool:status'),
(1, 'tool:update'),
(1, 'user:add'),
(1, 'user:delete'),
(1, 'user:menu'),
(1, 'user:page'),
(1, 'user:status'),
(1, 'user:update'),
(1, 'user:view')
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
('消息管理', '/messages', 'MailOutlined', 0, 10, true, 'message:menu')
ON CONFLICT (path) DO NOTHING;

-- 智能体管理：智能体列表
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('智能体列表', '/agents/list', 'UnorderedListOutlined', (SELECT id FROM agent_menu WHERE path='/agents'), 1, true, 'agent:page')
ON CONFLICT (path) DO NOTHING;

-- 助手智能体：问答 / 简历 / 考试
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('问答助手', '/agent/qa', 'CommentOutlined', (SELECT id FROM agent_menu WHERE path='/agent'), 1, true, 'qa:menu'),
('简历助手', '/agent/resume', 'ProfileOutlined', (SELECT id FROM agent_menu WHERE path='/agent'), 2, true, 'resume:menu'),
('考试助手', '/agent/exam', 'FileTextOutlined', (SELECT id FROM agent_menu WHERE path='/agent'), 3, true, 'exam:menu')
ON CONFLICT (path) DO NOTHING;

-- 问答助手：文件上传 / 问答结果 / QA问答 / 会话列表
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('文件列表', '/agent/qa/files', 'UploadOutlined', (SELECT id FROM agent_menu WHERE path='/agent/qa'), 1, true, 'qa_file:page'),
('问答结果', '/agent/qa/results', 'UnorderedListOutlined', (SELECT id FROM agent_menu WHERE path='/agent/qa'), 2, true, 'qa_result:page'),
('QA问答', '/agent/qa/chat', 'CommentOutlined', (SELECT id FROM agent_menu WHERE path='/agent/qa'), 3, true, 'qa:ask'),
('会话列表', '/agent/qa/sessions', 'MessageOutlined', (SELECT id FROM agent_menu WHERE path='/agent/qa'), 4, true, 'qa_session:page')
ON CONFLICT (path) DO NOTHING;

-- 简历助手：简历分析
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('简历分析', '/agent/resume/analysis', 'ProfileOutlined', (SELECT id FROM agent_menu WHERE path='/agent/resume'), 1, true, 'resume:page')
ON CONFLICT (path) DO NOTHING;

-- 考试助手：开始考试 / 考试结果
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('开始考试', '/agent/exam/start', 'FormOutlined', (SELECT id FROM agent_menu WHERE path='/agent/exam'), 1, true, 'exam:page'),
('考试结果', '/agent/exam/results', 'ProfileOutlined', (SELECT id FROM agent_menu WHERE path='/agent/exam'), 2, true, 'exam_result:page')
ON CONFLICT (path) DO NOTHING;

-- 面试助手：先插父节点，再插子菜单（同一条 INSERT 的子查询看不到刚插入的父行）
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('面试助手', '/agent/interview', 'CommentOutlined', (SELECT id FROM agent_menu WHERE path='/agent'), 4, true, 'interview:menu')
ON CONFLICT (path) DO NOTHING;

INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('面试结果', '/agent/interview/results', 'UnorderedListOutlined', (SELECT id FROM agent_menu WHERE path='/agent/interview'), 1, true, 'interview:page'),
('开始面试', '/agent/interview/start', 'FormOutlined', (SELECT id FROM agent_menu WHERE path='/agent/interview'), 2, true, 'interview:ask')
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
    agent_type, name, description, input_schema,
    enabled, version, create_user_id, update_user_id) VALUES
('qa', '问答助手', '智能问答与多轮对话', NULL,
    true, '1.0.0', (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin')),
('exam', '考试助手', '组卷、答题与评测', NULL,
    true, '1.0.0', (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin')),
('resume', '简历助手', '简历解析与优化建议', NULL,
    true, '1.0.0', (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin')),
('interview', '面试助手', '模拟面试与反馈', NULL,
    true, '1.0.0', (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin'))
ON CONFLICT (agent_type) DO NOTHING;

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
