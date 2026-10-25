-- ============================================================
-- agent-platform 数据库初始化脚本（PostgreSQL，可直接执行）
-- 本文件由 scripts/gen_schema.py 依据 backend/data/postgres 自动生成，请勿手改；
-- 模型变更后运行 `python scripts/gen_schema.py` 重新生成本文件。
--
-- 特性：① 数据库不存在则创建  ② 自动切换数据库  ③ 每表用 IF NOT EXISTS 存在判断（不删已有表）
--       ④ 表落入专属 agent_platform schema（CREATE SCHEMA + SET search_path，不污染 public）
--       ⑤ 末尾加载 RBAC 默认数据（幂等，可重复执行）。
-- 用法： psql -U <管理员> -h <host> -f scripts/schema.sql
--       首次执行需具备建库权限；重复执行安全（CREATE IF NOT EXISTS / INSERT ON CONFLICT）。
-- ============================================================

\set ON_ERROR_STOP on

-- ① 数据库不存在则创建（PostgreSQL 无 CREATE DATABASE IF NOT EXISTS，使用 \gexec 技巧）
SELECT 'CREATE DATABASE agent_platform WITH TEMPLATE template0 ENCODING ''UTF8'' LC_COLLATE ''C'' LC_CTYPE ''C'''
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'agent_platform')\gexec

-- ② 切换到目标库（后续所有语句均在 agent_platform 中执行）
\c agent_platform

-- ③ 创建专属 schema
CREATE SCHEMA IF NOT EXISTS agent_platform;

-- ④ 启用 UUID 生成函数（装入 agent_platform schema）
--    search_path 仅含 agent_platform，若扩展留在 public 会找不到 uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" SCHEMA agent_platform;

-- ⑤ 切换 search_path，后续对象全部落在 agent_platform
--    与应用连接 server_settings.search_path 保持一致，不占用 public
SET search_path TO agent_platform;

CREATE TABLE IF NOT EXISTS agent (
	id BIGSERIAL NOT NULL, 
	agent_type VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	description TEXT NOT NULL, 
	input_schema JSON, 
	enabled BOOLEAN DEFAULT true NOT NULL, 
	version VARCHAR(32) DEFAULT '1.0.0' NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (agent_type)
);

COMMENT ON TABLE "agent" IS 'Agent 元数据目录（全局）';
COMMENT ON COLUMN "agent".id IS '主键（代理键）';
COMMENT ON COLUMN "agent".agent_type IS 'Agent 类型（业务键，与 AgentRegistry.agent_type 一致）';
COMMENT ON COLUMN "agent".name IS 'Agent 展示名';
COMMENT ON COLUMN "agent".description IS 'Agent 说明';
COMMENT ON COLUMN "agent".input_schema IS '输入 JSON Schema（供校验与文档）';
COMMENT ON COLUMN "agent".enabled IS '全局启用开关（租户级开通见 agent_capability_policy）';
COMMENT ON COLUMN "agent".version IS '版本号';
COMMENT ON COLUMN "agent".create_at IS '创建时间';
COMMENT ON COLUMN "agent".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent".update_user_id IS '更新人ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_api_call_log (
	id BIGSERIAL NOT NULL, 
	trace_id VARCHAR(64), 
	caller VARCHAR(128), 
	user_id BIGINT, 
	tenant_id BIGINT, 
	method VARCHAR(16) NOT NULL, 
	path VARCHAR(512) NOT NULL, 
	route VARCHAR(512), 
	query_string VARCHAR(1024), 
	req_headers JSON, 
	req_time TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	status_code INTEGER, 
	resp_time TIMESTAMP WITHOUT TIME ZONE, 
	cost_ms INTEGER NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_path_time ON agent_api_call_log (path, req_time);

CREATE INDEX IF NOT EXISTS idx_req_time ON agent_api_call_log (req_time);

CREATE INDEX IF NOT EXISTS idx_trace ON agent_api_call_log (trace_id);

CREATE INDEX IF NOT EXISTS ix_agent_api_call_log_tenant_time ON agent_api_call_log (tenant_id, req_time);

COMMENT ON TABLE "agent_api_call_log" IS 'API调用日志（一次调用一行）';
COMMENT ON COLUMN "agent_api_call_log".id IS '主键';
COMMENT ON COLUMN "agent_api_call_log".trace_id IS '链路追踪ID（X-Trace-Id）';
COMMENT ON COLUMN "agent_api_call_log".caller IS '调用方（X-Forwarded-For首段/client host）';
COMMENT ON COLUMN "agent_api_call_log".user_id IS '用户ID（取自 JWT 的 user_id，BigInteger）';
COMMENT ON COLUMN "agent_api_call_log".tenant_id IS '租户ID（取自 JWT 的 tenant_id，可为空，BigInteger）';
COMMENT ON COLUMN "agent_api_call_log".method IS 'HTTP方法（GET/POST/...）';
COMMENT ON COLUMN "agent_api_call_log".path IS '请求路径（不含query）';
COMMENT ON COLUMN "agent_api_call_log".route IS '匹配路由模板（如/admin/files/{oss_key}）';
COMMENT ON COLUMN "agent_api_call_log".query_string IS '查询字符串';
COMMENT ON COLUMN "agent_api_call_log".req_headers IS '请求头（JSON；敏感头已脱敏）';
COMMENT ON COLUMN "agent_api_call_log".req_time IS '请求时间';
COMMENT ON COLUMN "agent_api_call_log".status_code IS 'HTTP状态码';
COMMENT ON COLUMN "agent_api_call_log".resp_time IS '响应时间';
COMMENT ON COLUMN "agent_api_call_log".cost_ms IS '耗时（毫秒）';
COMMENT ON COLUMN "agent_api_call_log".create_at IS '创建时间';
COMMENT ON COLUMN "agent_api_call_log".updated_at IS '更新时间（更新时由库触发器刷新）';

CREATE TABLE IF NOT EXISTS agent_audit_log (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	action VARCHAR(64) NOT NULL, 
	target VARCHAR(128) NOT NULL, 
	detail TEXT NOT NULL, 
	result VARCHAR(16) NOT NULL, 
	trace_id VARCHAR(64), 
	ip VARCHAR(64), 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_agent_audit_log_tenant_time ON agent_audit_log (tenant_id, create_at);

COMMENT ON TABLE "agent_audit_log" IS '审计日志（业务操作）';
COMMENT ON COLUMN "agent_audit_log".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_audit_log".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_audit_log".user_id IS '操作人（user_id，BigInteger）';
COMMENT ON COLUMN "agent_audit_log".action IS '操作类型';
COMMENT ON COLUMN "agent_audit_log".target IS '操作对象';
COMMENT ON COLUMN "agent_audit_log".detail IS '操作详情（JSON）';
COMMENT ON COLUMN "agent_audit_log".result IS '操作结果（成功/失败/待处理）';
COMMENT ON COLUMN "agent_audit_log".trace_id IS '链路追踪ID';
COMMENT ON COLUMN "agent_audit_log".ip IS '操作来源IP';
COMMENT ON COLUMN "agent_audit_log".create_at IS '创建时间';
COMMENT ON COLUMN "agent_audit_log".updated_at IS '更新时间（更新时由库触发器刷新）';

CREATE TABLE IF NOT EXISTS agent_capability_policy (
	id BIGSERIAL NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	agent_type VARCHAR(64) NOT NULL, 
	enabled BOOLEAN DEFAULT true NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	create_tenant_id BIGINT NOT NULL, 
	update_tenant_id BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_capability_tenant_agent UNIQUE (tenant_id, agent_type)
);

CREATE INDEX IF NOT EXISTS ix_agent_capability_policy_agent_type ON agent_capability_policy (agent_type);

CREATE INDEX IF NOT EXISTS ix_agent_capability_policy_tenant_id ON agent_capability_policy (tenant_id);

COMMENT ON TABLE "agent_capability_policy" IS '租户级 Agent 开通策略';
COMMENT ON COLUMN "agent_capability_policy".id IS '主键（代理键）';
COMMENT ON COLUMN "agent_capability_policy".tenant_id IS '租户ID（隔离边界）';
COMMENT ON COLUMN "agent_capability_policy".agent_type IS 'Agent 类型（逻辑外键→agent.agent_type，代码控制）';
COMMENT ON COLUMN "agent_capability_policy".enabled IS '该租户是否开通此 Agent';
COMMENT ON COLUMN "agent_capability_policy".create_at IS '创建时间';
COMMENT ON COLUMN "agent_capability_policy".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_capability_policy".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_capability_policy".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_capability_policy".create_tenant_id IS '创建租户ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_capability_policy".update_tenant_id IS '更新租户ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_config_change_request (
	id BIGSERIAL NOT NULL, 
	namespace VARCHAR(128) NOT NULL, 
	group_id VARCHAR(128) NOT NULL, 
	data_id VARCHAR(256) NOT NULL, 
	domain VARCHAR(32) NOT NULL, 
	op_type SMALLINT NOT NULL, 
	title VARCHAR(256), 
	content_new TEXT, 
	old_config_id BIGINT, 
	old_config_md5 VARCHAR(64), 
	old_history_nid BIGINT, 
	content_format VARCHAR(16) NOT NULL, 
	src_history_nid BIGINT, 
	status SMALLINT NOT NULL, 
	applicant_user_id BIGINT, 
	reviewer_user_id BIGINT, 
	reason VARCHAR(512), 
	nacos_history_nid BIGINT, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_agent_config_change_request_create_at ON agent_config_change_request (create_at);

CREATE INDEX IF NOT EXISTS idx_data ON agent_config_change_request (namespace, group_id, data_id);

CREATE INDEX IF NOT EXISTS idx_domain ON agent_config_change_request (domain);

CREATE INDEX IF NOT EXISTS idx_status ON agent_config_change_request (status);

COMMENT ON TABLE "agent_config_change_request" IS '配置变更申请（审批流，无tenant_id）';
COMMENT ON COLUMN "agent_config_change_request".id IS '主键';
COMMENT ON COLUMN "agent_config_change_request".namespace IS 'Nacos命名空间';
COMMENT ON COLUMN "agent_config_change_request".group_id IS 'Nacos分组';
COMMENT ON COLUMN "agent_config_change_request".data_id IS 'Nacos配置ID';
COMMENT ON COLUMN "agent_config_change_request".domain IS '业务域（如prompt）';
COMMENT ON COLUMN "agent_config_change_request".op_type IS '操作类型（1新增2修改3删除4回滚）';
COMMENT ON COLUMN "agent_config_change_request".title IS '标题';
COMMENT ON COLUMN "agent_config_change_request".content_new IS '拟下发内容（全文，审批前未进Nacos）';
COMMENT ON COLUMN "agent_config_change_request".old_config_id IS '变更前Nacos config_info.id（CAS基准引用）';
COMMENT ON COLUMN "agent_config_change_request".old_config_md5 IS '申请时Nacos当前md5（CAS基准）';
COMMENT ON COLUMN "agent_config_change_request".old_history_nid IS '执行后回填：变更前内容归档历史nid';
COMMENT ON COLUMN "agent_config_change_request".content_format IS '内容格式（json/text/yaml）';
COMMENT ON COLUMN "agent_config_change_request".src_history_nid IS '回滚来源历史nid';
COMMENT ON COLUMN "agent_config_change_request".status IS '状态（0待复核1通过2驳回3已执行）';
COMMENT ON COLUMN "agent_config_change_request".applicant_user_id IS '申请人user_id（BigInteger）';
COMMENT ON COLUMN "agent_config_change_request".reviewer_user_id IS '复核人user_id（BigInteger）';
COMMENT ON COLUMN "agent_config_change_request".reason IS '变更原因';
COMMENT ON COLUMN "agent_config_change_request".nacos_history_nid IS '执行后回填：新内容历史nid';
COMMENT ON COLUMN "agent_config_change_request".create_at IS '创建时间';
COMMENT ON COLUMN "agent_config_change_request".updated_at IS '更新时间（更新时由库触发器刷新）';

CREATE TABLE IF NOT EXISTS agent_config_review (
	id BIGSERIAL NOT NULL, 
	request_id BIGINT NOT NULL, 
	reviewer_user_id BIGINT, 
	action SMALLINT NOT NULL, 
	comment VARCHAR(512), 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_request ON agent_config_review (request_id);

COMMENT ON TABLE "agent_config_review" IS '配置复核记录（审批流，无tenant_id）';
COMMENT ON COLUMN "agent_config_review".id IS '主键';
COMMENT ON COLUMN "agent_config_review".request_id IS '关联申请ID';
COMMENT ON COLUMN "agent_config_review".reviewer_user_id IS '复核人user_id（BigInteger）';
COMMENT ON COLUMN "agent_config_review".action IS '动作（1通过2驳回）';
COMMENT ON COLUMN "agent_config_review".comment IS '复核意见';
COMMENT ON COLUMN "agent_config_review".create_at IS '创建时间';
COMMENT ON COLUMN "agent_config_review".updated_at IS '更新时间（更新时由库触发器刷新）';

CREATE TABLE IF NOT EXISTS agent_escalation (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	thread_id UUID NOT NULL, 
	reason VARCHAR(255) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	assigned_user_id BIGINT, 
	resolved_at TIMESTAMP WITHOUT TIME ZONE, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_agent_escalation_assigned_user_id ON agent_escalation (assigned_user_id);

CREATE INDEX IF NOT EXISTS ix_agent_escalation_tenant_id ON agent_escalation (tenant_id);

CREATE INDEX IF NOT EXISTS ix_agent_escalation_thread_id ON agent_escalation (thread_id);

CREATE INDEX IF NOT EXISTS ix_agent_escalation_user_id ON agent_escalation (user_id);

COMMENT ON TABLE "agent_escalation" IS '人工转接队列（HITL）';
COMMENT ON COLUMN "agent_escalation".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_escalation".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_escalation".user_id IS '用户ID（转接人，BigInteger）';
COMMENT ON COLUMN "agent_escalation".thread_id IS '关联会话ID';
COMMENT ON COLUMN "agent_escalation".reason IS '转接原因';
COMMENT ON COLUMN "agent_escalation".status IS '状态（pending/resolved）';
COMMENT ON COLUMN "agent_escalation".assigned_user_id IS '处理人ID（user_id，未分配为空）';
COMMENT ON COLUMN "agent_escalation".resolved_at IS '解决时间';
COMMENT ON COLUMN "agent_escalation".create_at IS '创建时间';
COMMENT ON COLUMN "agent_escalation".updated_at IS '更新时间（更新时由库触发器刷新）';

CREATE TABLE IF NOT EXISTS agent_exam_reviews (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	submission_id UUID NOT NULL, 
	question_id UUID NOT NULL, 
	question_type VARCHAR(16) NOT NULL, 
	knowledge_tag VARCHAR(128) NOT NULL, 
	student_answer TEXT NOT NULL, 
	ai_score INTEGER NOT NULL, 
	ai_feedback TEXT NOT NULL, 
	ai_raw_result JSON NOT NULL, 
	teacher_score INTEGER NOT NULL, 
	teacher_comment TEXT NOT NULL, 
	final_score INTEGER NOT NULL, 
	needs_review BOOLEAN NOT NULL, 
	reviewed_user_id BIGINT NOT NULL, 
	reviewed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	create_tenant_id BIGINT NOT NULL, 
	update_tenant_id BIGINT NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_exam_reviews_knowledge_tag ON agent_exam_reviews (knowledge_tag);

CREATE INDEX IF NOT EXISTS idx_exam_reviews_submission_id ON agent_exam_reviews (submission_id);

COMMENT ON TABLE "agent_exam_reviews" IS '试卷批改明细（每题一条）';
COMMENT ON COLUMN "agent_exam_reviews".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_exam_reviews".submission_id IS '提交记录ID';
COMMENT ON COLUMN "agent_exam_reviews".question_id IS '题目ID';
COMMENT ON COLUMN "agent_exam_reviews".question_type IS '题型';
COMMENT ON COLUMN "agent_exam_reviews".knowledge_tag IS '知识点标签';
COMMENT ON COLUMN "agent_exam_reviews".student_answer IS '学生作答';
COMMENT ON COLUMN "agent_exam_reviews".ai_score IS 'AI 评分';
COMMENT ON COLUMN "agent_exam_reviews".ai_feedback IS 'AI 反馈';
COMMENT ON COLUMN "agent_exam_reviews".ai_raw_result IS 'AI 原始结果（JSON）';
COMMENT ON COLUMN "agent_exam_reviews".teacher_score IS '教师评分';
COMMENT ON COLUMN "agent_exam_reviews".teacher_comment IS '教师评语';
COMMENT ON COLUMN "agent_exam_reviews".final_score IS '最终得分';
COMMENT ON COLUMN "agent_exam_reviews".needs_review IS '是否需要人工复核';
COMMENT ON COLUMN "agent_exam_reviews".reviewed_user_id IS '复核人ID（user_id，BigInteger）';
COMMENT ON COLUMN "agent_exam_reviews".reviewed_at IS '复核时间';
COMMENT ON COLUMN "agent_exam_reviews".create_at IS '创建时间';
COMMENT ON COLUMN "agent_exam_reviews".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_exam_reviews".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_exam_reviews".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_exam_reviews".create_tenant_id IS '创建租户ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_exam_reviews".update_tenant_id IS '更新租户ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_exam_submissions (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	exam_id UUID NOT NULL, 
	user_id BIGINT NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	word_minio_path VARCHAR(512) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	submitted_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	published_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	weak_points JSON NOT NULL, 
	weak_points_summary TEXT NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	create_tenant_id BIGINT NOT NULL, 
	update_tenant_id BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_exam_submissions_exam_student UNIQUE (exam_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_exam_submissions_exam_id ON agent_exam_submissions (exam_id);

CREATE INDEX IF NOT EXISTS idx_exam_submissions_status ON agent_exam_submissions (status);

CREATE INDEX IF NOT EXISTS idx_exam_submissions_user_id ON agent_exam_submissions (user_id);

COMMENT ON TABLE "agent_exam_submissions" IS '试卷提交记录';
COMMENT ON COLUMN "agent_exam_submissions".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_exam_submissions".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_exam_submissions".exam_id IS '试卷ID';
COMMENT ON COLUMN "agent_exam_submissions".user_id IS '用户ID（user_id，BigInteger）';
COMMENT ON COLUMN "agent_exam_submissions".source IS '来源（word/online/miniapp）';
COMMENT ON COLUMN "agent_exam_submissions".word_minio_path IS 'Word 文件 MinIO 路径';
COMMENT ON COLUMN "agent_exam_submissions".status IS '状态（submitted/ai_processing/pending_review/reviewed/published）';
COMMENT ON COLUMN "agent_exam_submissions".submitted_at IS '提交时间';
COMMENT ON COLUMN "agent_exam_submissions".published_at IS '发布时间';
COMMENT ON COLUMN "agent_exam_submissions".weak_points IS '薄弱点（JSON）';
COMMENT ON COLUMN "agent_exam_submissions".weak_points_summary IS '薄弱点摘要';
COMMENT ON COLUMN "agent_exam_submissions".create_at IS '创建时间';
COMMENT ON COLUMN "agent_exam_submissions".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_exam_submissions".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_exam_submissions".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_exam_submissions".create_tenant_id IS '创建租户ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_exam_submissions".update_tenant_id IS '更新租户ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_exams (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	title VARCHAR(256) NOT NULL, 
	description TEXT NOT NULL, 
	due_date TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	created_user_id BIGINT NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	create_tenant_id BIGINT NOT NULL, 
	update_tenant_id BIGINT NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_exams_tenant_id ON agent_exams (tenant_id);

COMMENT ON TABLE "agent_exams" IS '试卷定义';
COMMENT ON COLUMN "agent_exams".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_exams".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_exams".title IS '标题';
COMMENT ON COLUMN "agent_exams".description IS '描述';
COMMENT ON COLUMN "agent_exams".due_date IS '截止时间';
COMMENT ON COLUMN "agent_exams".created_user_id IS '创建人ID（user_id，BigInteger）';
COMMENT ON COLUMN "agent_exams".is_active IS '是否启用';
COMMENT ON COLUMN "agent_exams".create_at IS '创建时间';
COMMENT ON COLUMN "agent_exams".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_exams".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_exams".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_exams".create_tenant_id IS '创建租户ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_exams".update_tenant_id IS '更新租户ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_interview_questions (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	content TEXT NOT NULL, 
	difficulty VARCHAR(8) NOT NULL, 
	tags JSON NOT NULL, 
	target_position VARCHAR(128) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_user_id BIGINT NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	create_tenant_id BIGINT NOT NULL, 
	update_tenant_id BIGINT NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_interview_questions_difficulty ON agent_interview_questions (difficulty);

CREATE INDEX IF NOT EXISTS idx_interview_questions_target_position ON agent_interview_questions (target_position);

CREATE INDEX IF NOT EXISTS idx_interview_questions_tenant_id ON agent_interview_questions (tenant_id);

COMMENT ON TABLE "agent_interview_questions" IS '面试题库';
COMMENT ON COLUMN "agent_interview_questions".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_interview_questions".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_interview_questions".content IS '题目内容';
COMMENT ON COLUMN "agent_interview_questions".difficulty IS '难度（easy/medium/hard）';
COMMENT ON COLUMN "agent_interview_questions".tags IS '标签（JSON）';
COMMENT ON COLUMN "agent_interview_questions".target_position IS '目标岗位';
COMMENT ON COLUMN "agent_interview_questions".is_active IS '是否启用';
COMMENT ON COLUMN "agent_interview_questions".created_user_id IS '创建人ID（user_id，BigInteger）';
COMMENT ON COLUMN "agent_interview_questions".create_at IS '创建时间';
COMMENT ON COLUMN "agent_interview_questions".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_interview_questions".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_interview_questions".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_interview_questions".create_tenant_id IS '创建租户ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_interview_questions".update_tenant_id IS '更新租户ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_interview_sessions (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	session_id VARCHAR(128) NOT NULL, 
	thread_id UUID NOT NULL, 
	target_position VARCHAR(128) NOT NULL, 
	resume_review_id UUID NOT NULL, 
	summary TEXT NOT NULL, 
	report JSON NOT NULL, 
	overall_score INTEGER NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	finished_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	create_tenant_id BIGINT NOT NULL, 
	update_tenant_id BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_interview_sessions_thread UNIQUE (thread_id)
);

CREATE INDEX IF NOT EXISTS idx_interview_sessions_tenant_id ON agent_interview_sessions (tenant_id);

CREATE INDEX IF NOT EXISTS idx_interview_sessions_user_id ON agent_interview_sessions (user_id);

COMMENT ON TABLE "agent_interview_sessions" IS '模拟面试会话';
COMMENT ON COLUMN "agent_interview_sessions".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_interview_sessions".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_interview_sessions".user_id IS '用户ID（user_id，BigInteger）';
COMMENT ON COLUMN "agent_interview_sessions".session_id IS '会话标识';
COMMENT ON COLUMN "agent_interview_sessions".thread_id IS '关联 agent_thread.id（会话）';
COMMENT ON COLUMN "agent_interview_sessions".target_position IS '目标岗位';
COMMENT ON COLUMN "agent_interview_sessions".resume_review_id IS '关联简历审查ID';
COMMENT ON COLUMN "agent_interview_sessions".summary IS '摘要';
COMMENT ON COLUMN "agent_interview_sessions".report IS '面试报告（JSON）';
COMMENT ON COLUMN "agent_interview_sessions".overall_score IS '综合得分';
COMMENT ON COLUMN "agent_interview_sessions".status IS '状态（in_progress/finished）';
COMMENT ON COLUMN "agent_interview_sessions".finished_at IS '结束时间';
COMMENT ON COLUMN "agent_interview_sessions".create_at IS '创建时间';
COMMENT ON COLUMN "agent_interview_sessions".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_interview_sessions".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_interview_sessions".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_interview_sessions".create_tenant_id IS '创建租户ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_interview_sessions".update_tenant_id IS '更新租户ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_knowledge_pending_queue (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	question TEXT NOT NULL, 
	user_id BIGINT NOT NULL, 
	confidence FLOAT NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	resolved_user_id BIGINT NOT NULL, 
	resolved_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	create_tenant_id BIGINT NOT NULL, 
	update_tenant_id BIGINT NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_kpq_status ON agent_knowledge_pending_queue (status);

CREATE INDEX IF NOT EXISTS idx_kpq_tenant_id ON agent_knowledge_pending_queue (tenant_id);

COMMENT ON TABLE "agent_knowledge_pending_queue" IS '知识库待补充队列';
COMMENT ON COLUMN "agent_knowledge_pending_queue".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_knowledge_pending_queue".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_knowledge_pending_queue".question IS '待补充问题';
COMMENT ON COLUMN "agent_knowledge_pending_queue".user_id IS '提交用户ID（user_id，BigInteger）';
COMMENT ON COLUMN "agent_knowledge_pending_queue".confidence IS '置信度';
COMMENT ON COLUMN "agent_knowledge_pending_queue".status IS '状态（pending/resolved/dismissed）';
COMMENT ON COLUMN "agent_knowledge_pending_queue".resolved_user_id IS '处理人ID（user_id，BigInteger）';
COMMENT ON COLUMN "agent_knowledge_pending_queue".resolved_at IS '解决时间';
COMMENT ON COLUMN "agent_knowledge_pending_queue".create_at IS '创建时间';
COMMENT ON COLUMN "agent_knowledge_pending_queue".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_knowledge_pending_queue".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_knowledge_pending_queue".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_knowledge_pending_queue".create_tenant_id IS '创建租户ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_knowledge_pending_queue".update_tenant_id IS '更新租户ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_login_log (
	id BIGSERIAL NOT NULL, 
	user_id BIGINT, 
	username VARCHAR(64), 
	tenant_id BIGINT, 
	login_type VARCHAR(16) DEFAULT 'password' NOT NULL, 
	success BOOLEAN NOT NULL, 
	fail_reason VARCHAR(128), 
	ip VARCHAR(64), 
	user_agent VARCHAR(512), 
	client VARCHAR(64), 
	trace_id VARCHAR(64), 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_agent_login_log_create_at ON agent_login_log (create_at);

CREATE INDEX IF NOT EXISTS ix_agent_login_log_tenant_time ON agent_login_log (tenant_id, create_at);

CREATE INDEX IF NOT EXISTS ix_agent_login_log_user_time ON agent_login_log (user_id, create_at);

COMMENT ON TABLE "agent_login_log" IS '登录日志（每次登录尝试一行，成功与失败都记）';
COMMENT ON COLUMN "agent_login_log".id IS '主键';
COMMENT ON COLUMN "agent_login_log".user_id IS '用户ID（登录失败时可能为空）';
COMMENT ON COLUMN "agent_login_log".username IS '尝试登录的用户名（失败时保留输入值，用于排查撞库）';
COMMENT ON COLUMN "agent_login_log".tenant_id IS '租户ID（超管与失败为空）';
COMMENT ON COLUMN "agent_login_log".login_type IS '登录方式（password/sso）';
COMMENT ON COLUMN "agent_login_log".success IS '是否登录成功';
COMMENT ON COLUMN "agent_login_log".fail_reason IS '失败原因';
COMMENT ON COLUMN "agent_login_log".ip IS '客户端IP（X-Forwarded-For首段优先）';
COMMENT ON COLUMN "agent_login_log".user_agent IS 'User-Agent原文';
COMMENT ON COLUMN "agent_login_log".client IS '从 UA 解析出的客户端（如 Chrome / Windows）';
COMMENT ON COLUMN "agent_login_log".trace_id IS '链路追踪ID';
COMMENT ON COLUMN "agent_login_log".create_at IS '登录时间';

CREATE TABLE IF NOT EXISTS agent_long_term_memory (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	agent_id VARCHAR(64) NOT NULL, 
	block VARCHAR(32) NOT NULL, 
	content TEXT NOT NULL, 
	embedding_id VARCHAR(64) NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_agent_long_term_memory_tenant_id ON agent_long_term_memory (tenant_id);

CREATE INDEX IF NOT EXISTS ix_agent_long_term_memory_user_id ON agent_long_term_memory (user_id);

COMMENT ON TABLE "agent_long_term_memory" IS '长期记忆块';
COMMENT ON COLUMN "agent_long_term_memory".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_long_term_memory".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_long_term_memory".user_id IS '用户ID（记忆用户，BigInteger）';
COMMENT ON COLUMN "agent_long_term_memory".agent_id IS '智能体ID';
COMMENT ON COLUMN "agent_long_term_memory".block IS '记忆块类型（persona/fact/preference/summary）';
COMMENT ON COLUMN "agent_long_term_memory".content IS '记忆内容';
COMMENT ON COLUMN "agent_long_term_memory".embedding_id IS '向量库ID';
COMMENT ON COLUMN "agent_long_term_memory".create_at IS '创建时间';
COMMENT ON COLUMN "agent_long_term_memory".updated_at IS '更新时间（更新时由库触发器刷新）';

CREATE TABLE IF NOT EXISTS agent_menu (
	id BIGSERIAL NOT NULL, 
	name VARCHAR(64) NOT NULL, 
	path VARCHAR(128) NOT NULL, 
	icon VARCHAR(64) DEFAULT '' NOT NULL, 
	parent_id BIGINT DEFAULT 0 NOT NULL, 
	sort_order INTEGER DEFAULT 0 NOT NULL, 
	visible BOOLEAN DEFAULT true NOT NULL, 
	scope VARCHAR(64), 
	PRIMARY KEY (id)
);

COMMENT ON TABLE "agent_menu" IS '前端菜单（登录后按权限下发）';
COMMENT ON COLUMN "agent_menu".id IS '菜单ID';
COMMENT ON COLUMN "agent_menu".name IS '菜单名称（前端展示）';
COMMENT ON COLUMN "agent_menu".path IS '前端路由路径';
COMMENT ON COLUMN "agent_menu".icon IS '图标名（前端展示用，如 DashboardOutlined）';
COMMENT ON COLUMN "agent_menu".parent_id IS '父菜单ID（0=顶级菜单）';
COMMENT ON COLUMN "agent_menu".sort_order IS '排序号（升序）';
COMMENT ON COLUMN "agent_menu".visible IS '是否显示';
COMMENT ON COLUMN "agent_menu".scope IS '访问该菜单所需权限点（NULL=登录即可见）';

CREATE TABLE IF NOT EXISTS agent_message (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	thread_id UUID NOT NULL, 
	run_id UUID, 
	role VARCHAR(32) NOT NULL, 
	type VARCHAR(32) NOT NULL, 
	payload TEXT NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_agent_message_tenant_id ON agent_message (tenant_id);

CREATE INDEX IF NOT EXISTS ix_agent_message_thread_id ON agent_message (thread_id);

CREATE INDEX IF NOT EXISTS ix_agent_message_user_id ON agent_message (user_id);

COMMENT ON TABLE "agent_message" IS '消息轨迹（append-only）';
COMMENT ON COLUMN "agent_message".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_message".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_message".user_id IS '归属用户ID（冗余，BigInteger）';
COMMENT ON COLUMN "agent_message".thread_id IS '关联会话ID';
COMMENT ON COLUMN "agent_message".run_id IS '关联运行ID';
COMMENT ON COLUMN "agent_message".role IS '角色（user/assistant/system/tool）';
COMMENT ON COLUMN "agent_message".type IS '消息类型';
COMMENT ON COLUMN "agent_message".payload IS '消息内容（JSON）';
COMMENT ON COLUMN "agent_message".create_at IS '创建时间';
COMMENT ON COLUMN "agent_message".updated_at IS '更新时间（更新时由库触发器刷新）';

CREATE TABLE IF NOT EXISTS agent_model (
	agent_id BIGINT NOT NULL, 
	model_id BIGINT NOT NULL, 
	is_default BOOLEAN DEFAULT false NOT NULL, 
	priority INTEGER DEFAULT 0 NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	PRIMARY KEY (agent_id, model_id)
);

COMMENT ON TABLE "agent_model" IS 'Agent 与模型的多对多绑定（agent 级模型覆盖，全局表）';
COMMENT ON COLUMN "agent_model".agent_id IS '逻辑外键 → agent.id';
COMMENT ON COLUMN "agent_model".model_id IS '逻辑外键 → model_registry.id';
COMMENT ON COLUMN "agent_model".is_default IS '同类模型中的默认项（覆盖全局默认时优先取此项）';
COMMENT ON COLUMN "agent_model".priority IS '同类多模型的优先顺序，越小越优先';
COMMENT ON COLUMN "agent_model".create_at IS '创建时间';
COMMENT ON COLUMN "agent_model".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_model".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_model".update_user_id IS '更新人ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_model_registry (
	id BIGSERIAL NOT NULL, 
	model_type VARCHAR(32) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	provider VARCHAR(64), 
	base_url VARCHAR(512), 
	api_key VARCHAR(512), 
	endpoint_path VARCHAR(512), 
	temperature FLOAT, 
	timeout_s FLOAT, 
	max_retries INTEGER, 
	enabled BOOLEAN DEFAULT true NOT NULL, 
	sort_order INTEGER DEFAULT 0 NOT NULL, 
	description TEXT, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_model_registry_type_name UNIQUE (model_type, name)
);

CREATE INDEX IF NOT EXISTS ix_agent_model_registry_model_type ON agent_model_registry (model_type);

COMMENT ON TABLE "agent_model_registry" IS '模型配置注册表（平台级全局资源，不分租户）';
COMMENT ON COLUMN "agent_model_registry".id IS '主键（代理键）';
COMMENT ON COLUMN "agent_model_registry".model_type IS '用途分类：llm / embedding / reranker / classifier';
COMMENT ON COLUMN "agent_model_registry".name IS '模型标识（如 deepseek-chat / bge-m3）';
COMMENT ON COLUMN "agent_model_registry".provider IS '厂商（openai / dashscope / local），可空';
COMMENT ON COLUMN "agent_model_registry".base_url IS '远程 API 基址；本地模型改用 endpoint_path';
COMMENT ON COLUMN "agent_model_registry".api_key IS 'API 密钥（敏感，可空）';
COMMENT ON COLUMN "agent_model_registry".endpoint_path IS '本地模型路径（classifier_dir 类）';
COMMENT ON COLUMN "agent_model_registry".temperature IS 'LLM 采样温度（仅 llm 用）';
COMMENT ON COLUMN "agent_model_registry".timeout_s IS '调用超时（秒）';
COMMENT ON COLUMN "agent_model_registry".max_retries IS '失败重试次数';
COMMENT ON COLUMN "agent_model_registry".enabled IS '是否启用';
COMMENT ON COLUMN "agent_model_registry".sort_order IS '同类排序（前端下拉 / 默认选择）';
COMMENT ON COLUMN "agent_model_registry".description IS '备注';
COMMENT ON COLUMN "agent_model_registry".create_at IS '创建时间';
COMMENT ON COLUMN "agent_model_registry".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_model_registry".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_model_registry".update_user_id IS '更新人ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_plugin (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	name VARCHAR(64) NOT NULL, 
	version VARCHAR(32) NOT NULL, 
	capabilities TEXT NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	config TEXT NOT NULL, 
	registered_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	create_tenant_id BIGINT NOT NULL, 
	update_tenant_id BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS ix_agent_plugin_tenant_id ON agent_plugin (tenant_id);

COMMENT ON TABLE "agent_plugin" IS '插件注册表';
COMMENT ON COLUMN "agent_plugin".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_plugin".name IS '插件名';
COMMENT ON COLUMN "agent_plugin".version IS '版本';
COMMENT ON COLUMN "agent_plugin".capabilities IS '能力列表（JSON）';
COMMENT ON COLUMN "agent_plugin".status IS '状态（enabled/disabled）';
COMMENT ON COLUMN "agent_plugin".config IS '配置（JSON）';
COMMENT ON COLUMN "agent_plugin".registered_at IS '注册时间';
COMMENT ON COLUMN "agent_plugin".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_plugin".user_id IS '维护人user_id（BigInteger，前端显式维护）';
COMMENT ON COLUMN "agent_plugin".create_at IS '创建时间';
COMMENT ON COLUMN "agent_plugin".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_plugin".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_plugin".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_plugin".create_tenant_id IS '创建租户ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_plugin".update_tenant_id IS '更新租户ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_qa_sessions (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	thread_id UUID NOT NULL, 
	summary TEXT NOT NULL, 
	summary_version INTEGER NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	create_tenant_id BIGINT NOT NULL, 
	update_tenant_id BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_qa_sessions_thread UNIQUE (thread_id)
);

CREATE INDEX IF NOT EXISTS idx_qa_sessions_tenant_id ON agent_qa_sessions (tenant_id);

CREATE INDEX IF NOT EXISTS idx_qa_sessions_user_id ON agent_qa_sessions (user_id);

COMMENT ON TABLE "agent_qa_sessions" IS '问答会话';
COMMENT ON COLUMN "agent_qa_sessions".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_qa_sessions".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_qa_sessions".user_id IS '用户ID（user_id，BigInteger）';
COMMENT ON COLUMN "agent_qa_sessions".thread_id IS '关联 agent_thread.id（会话）';
COMMENT ON COLUMN "agent_qa_sessions".summary IS '摘要';
COMMENT ON COLUMN "agent_qa_sessions".summary_version IS '摘要版本';
COMMENT ON COLUMN "agent_qa_sessions".create_at IS '创建时间';
COMMENT ON COLUMN "agent_qa_sessions".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_qa_sessions".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_qa_sessions".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_qa_sessions".create_tenant_id IS '创建租户ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_qa_sessions".update_tenant_id IS '更新租户ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_questions (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	exam_id UUID NOT NULL, 
	question_no INTEGER NOT NULL, 
	question_type VARCHAR(16) NOT NULL, 
	content TEXT NOT NULL, 
	correct_answer TEXT NOT NULL, 
	score INTEGER NOT NULL, 
	knowledge_tag VARCHAR(128) NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	create_tenant_id BIGINT NOT NULL, 
	update_tenant_id BIGINT NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_questions_exam_id ON agent_questions (exam_id);

CREATE INDEX IF NOT EXISTS idx_questions_knowledge_tag ON agent_questions (knowledge_tag);

COMMENT ON TABLE "agent_questions" IS '试卷题目';
COMMENT ON COLUMN "agent_questions".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_questions".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_questions".exam_id IS '所属试卷ID';
COMMENT ON COLUMN "agent_questions".question_no IS '题号';
COMMENT ON COLUMN "agent_questions".question_type IS '题型（single_choice/multi_choice/judge/short_answer/code）';
COMMENT ON COLUMN "agent_questions".content IS '题干';
COMMENT ON COLUMN "agent_questions".correct_answer IS '标准答案';
COMMENT ON COLUMN "agent_questions".score IS '分值';
COMMENT ON COLUMN "agent_questions".knowledge_tag IS '知识点标签';
COMMENT ON COLUMN "agent_questions".create_at IS '创建时间';
COMMENT ON COLUMN "agent_questions".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_questions".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_questions".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_questions".create_tenant_id IS '创建租户ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_questions".update_tenant_id IS '更新租户ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_resume_reviews (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	pdf_minio_path VARCHAR(512) NOT NULL, 
	structured_data JSON NOT NULL, 
	scores JSON NOT NULL, 
	issues JSON NOT NULL, 
	summary JSON NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	error_msg TEXT NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	create_tenant_id BIGINT NOT NULL, 
	update_tenant_id BIGINT NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_resume_reviews_status ON agent_resume_reviews (status);

CREATE INDEX IF NOT EXISTS idx_resume_reviews_tenant_id ON agent_resume_reviews (tenant_id);

CREATE INDEX IF NOT EXISTS idx_resume_reviews_user_id ON agent_resume_reviews (user_id);

COMMENT ON TABLE "agent_resume_reviews" IS '简历审查结果';
COMMENT ON COLUMN "agent_resume_reviews".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_resume_reviews".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_resume_reviews".user_id IS '用户ID（user_id，BigInteger）';
COMMENT ON COLUMN "agent_resume_reviews".pdf_minio_path IS 'PDF 文件 MinIO 路径';
COMMENT ON COLUMN "agent_resume_reviews".structured_data IS '结构化信息（JSON）';
COMMENT ON COLUMN "agent_resume_reviews".scores IS '评分（JSON）';
COMMENT ON COLUMN "agent_resume_reviews".issues IS '问题清单（JSON）';
COMMENT ON COLUMN "agent_resume_reviews".summary IS '摘要（JSON）';
COMMENT ON COLUMN "agent_resume_reviews".status IS '状态（pending/processing/done/failed）';
COMMENT ON COLUMN "agent_resume_reviews".error_msg IS '错误信息';
COMMENT ON COLUMN "agent_resume_reviews".create_at IS '创建时间';
COMMENT ON COLUMN "agent_resume_reviews".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_resume_reviews".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_resume_reviews".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_resume_reviews".create_tenant_id IS '创建租户ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_resume_reviews".update_tenant_id IS '更新租户ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_role (
	id BIGSERIAL NOT NULL, 
	role_id INTEGER NOT NULL, 
	name VARCHAR(64) NOT NULL, 
	description TEXT NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (role_id)
);

COMMENT ON TABLE "agent_role" IS '角色目录（全局）';
COMMENT ON COLUMN "agent_role".id IS '主键（代理键）';
COMMENT ON COLUMN "agent_role".role_id IS '角色ID（整数业务键，见 DEFAULT_ROLES）';
COMMENT ON COLUMN "agent_role".name IS '角色展示名';
COMMENT ON COLUMN "agent_role".description IS '角色说明';
COMMENT ON COLUMN "agent_role".create_at IS '创建时间';
COMMENT ON COLUMN "agent_role".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_role".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_role".update_user_id IS '更新人ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_role_permission (
	role_id INTEGER NOT NULL, 
	scope VARCHAR(128) NOT NULL, 
	PRIMARY KEY (role_id, scope)
);

COMMENT ON TABLE "agent_role_permission" IS '角色→权限点映射（多对多中间表）';
COMMENT ON COLUMN "agent_role_permission".role_id IS '角色ID（整数；逻辑外键→agent_role.role_id，代码控制）';
COMMENT ON COLUMN "agent_role_permission".scope IS '权限点（资源:动作，如 qa:ask）';

CREATE TABLE IF NOT EXISTS agent_run (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	thread_id UUID NOT NULL, 
	graph_name VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	prompt_tokens INTEGER NOT NULL, 
	completion_tokens INTEGER NOT NULL, 
	cost_cents INTEGER NOT NULL, 
	started_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	ended_at TIMESTAMP WITHOUT TIME ZONE, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_agent_run_tenant_id ON agent_run (tenant_id);

CREATE INDEX IF NOT EXISTS ix_agent_run_tenant_time ON agent_run (tenant_id, create_at);

CREATE INDEX IF NOT EXISTS ix_agent_run_thread_id ON agent_run (thread_id);

CREATE INDEX IF NOT EXISTS ix_agent_run_user_id ON agent_run (user_id);

COMMENT ON TABLE "agent_run" IS '运行台账（token/成本/延迟）';
COMMENT ON COLUMN "agent_run".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_run".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_run".user_id IS '归属用户ID（冗余，BigInteger）';
COMMENT ON COLUMN "agent_run".thread_id IS '关联会话ID';
COMMENT ON COLUMN "agent_run".graph_name IS '运行的图名称';
COMMENT ON COLUMN "agent_run".status IS '运行状态（running/done/error）';
COMMENT ON COLUMN "agent_run".prompt_tokens IS '输入token数';
COMMENT ON COLUMN "agent_run".completion_tokens IS '输出token数';
COMMENT ON COLUMN "agent_run".cost_cents IS '成本（分）';
COMMENT ON COLUMN "agent_run".started_at IS '开始时间';
COMMENT ON COLUMN "agent_run".ended_at IS '结束时间';
COMMENT ON COLUMN "agent_run".create_at IS '创建时间';
COMMENT ON COLUMN "agent_run".updated_at IS '更新时间（更新时由库触发器刷新）';

CREATE TABLE IF NOT EXISTS agent_scoring_points (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	question_id UUID NOT NULL, 
	point_desc TEXT NOT NULL, 
	point_score INTEGER NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	confirmed_user_id BIGINT NOT NULL, 
	confirmed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	create_user_id BIGINT NOT NULL, 
	update_user_id BIGINT NOT NULL, 
	create_tenant_id BIGINT NOT NULL, 
	update_tenant_id BIGINT NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_scoring_points_question_id ON agent_scoring_points (question_id);

COMMENT ON TABLE "agent_scoring_points" IS '题目评分点';
COMMENT ON COLUMN "agent_scoring_points".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_scoring_points".question_id IS '题目ID';
COMMENT ON COLUMN "agent_scoring_points".point_desc IS '评分点描述';
COMMENT ON COLUMN "agent_scoring_points".point_score IS '评分点分值';
COMMENT ON COLUMN "agent_scoring_points".is_active IS '是否启用';
COMMENT ON COLUMN "agent_scoring_points".confirmed_user_id IS '确认人ID（user_id，BigInteger）';
COMMENT ON COLUMN "agent_scoring_points".confirmed_at IS '确认时间';
COMMENT ON COLUMN "agent_scoring_points".create_at IS '创建时间';
COMMENT ON COLUMN "agent_scoring_points".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_scoring_points".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_scoring_points".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_scoring_points".create_tenant_id IS '创建租户ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_scoring_points".update_tenant_id IS '更新租户ID（写 SQL 时注入）';

CREATE TABLE IF NOT EXISTS agent_tenant (
	id BIGSERIAL NOT NULL, 
	name VARCHAR(64) NOT NULL, 
	enabled BOOLEAN DEFAULT true NOT NULL, 
	is_primary BOOLEAN DEFAULT false NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_tenant_primary ON agent_tenant (is_primary) WHERE is_primary;

COMMENT ON TABLE "agent_tenant" IS '租户（隔离边界，登录响应与菜单展示用）';
COMMENT ON COLUMN "agent_tenant".id IS '租户ID（与全局 tenant_id 对齐）';
COMMENT ON COLUMN "agent_tenant".name IS '租户显示名';
COMMENT ON COLUMN "agent_tenant".enabled IS '是否启用；停用后不可登录、不可切换，数据保留';
COMMENT ON COLUMN "agent_tenant".is_primary IS '主租户标记；仅主租户允许存在 role_id=3 的超管，且不可停用';
COMMENT ON COLUMN "agent_tenant".create_at IS '创建时间';
COMMENT ON COLUMN "agent_tenant".updated_at IS '更新时间（更新时由库触发器刷新）';

CREATE TABLE IF NOT EXISTS agent_thread (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	graph_name VARCHAR(64) NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_agent_thread_tenant_id ON agent_thread (tenant_id);

CREATE INDEX IF NOT EXISTS ix_agent_thread_tenant_status_time ON agent_thread (tenant_id, status, updated_at);

CREATE INDEX IF NOT EXISTS ix_agent_thread_tenant_user ON agent_thread (tenant_id, user_id);

CREATE INDEX IF NOT EXISTS ix_agent_thread_user_id ON agent_thread (user_id);

COMMENT ON TABLE "agent_thread" IS '会话/任务';
COMMENT ON COLUMN "agent_thread".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_thread".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_thread".user_id IS '归属用户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_thread".status IS '状态（active/archived）';
COMMENT ON COLUMN "agent_thread".graph_name IS '运行的图名称';
COMMENT ON COLUMN "agent_thread".create_at IS '创建时间';
COMMENT ON COLUMN "agent_thread".updated_at IS '更新时间（更新时由库触发器刷新）';

CREATE TABLE IF NOT EXISTS agent_tool (
	id UUID DEFAULT uuid_generate_v4() NOT NULL, 
	name VARCHAR(64) NOT NULL, 
	plugin VARCHAR(64) NOT NULL, 
	description TEXT NOT NULL, 
	schema TEXT NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

COMMENT ON TABLE "agent_tool" IS '工具目录';
COMMENT ON COLUMN "agent_tool".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_tool".name IS '工具名';
COMMENT ON COLUMN "agent_tool".plugin IS '所属插件';
COMMENT ON COLUMN "agent_tool".description IS '描述';
COMMENT ON COLUMN "agent_tool".schema IS '工具Schema（JSON）';
COMMENT ON COLUMN "agent_tool".create_at IS '创建时间';
COMMENT ON COLUMN "agent_tool".updated_at IS '更新时间（更新时由库触发器刷新）';

CREATE TABLE IF NOT EXISTS "agent_user" (
	id BIGSERIAL NOT NULL, 
	username VARCHAR(64) NOT NULL, 
	name VARCHAR(64) NOT NULL, 
	password VARCHAR(128) NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_agent_user_tenant_id ON "agent_user" (tenant_id);

CREATE UNIQUE INDEX IF NOT EXISTS uk_user_username ON "agent_user" (username);

COMMENT ON TABLE "agent_user" IS '账号（登录认证主表）';
COMMENT ON COLUMN "agent_user".id IS '用户ID（与全局 user_id 对齐）';
COMMENT ON COLUMN "agent_user".username IS '登录名（唯一），登录只查该列';
COMMENT ON COLUMN "agent_user".name IS '显示名，不参与登录，不要求唯一';
COMMENT ON COLUMN "agent_user".password IS '明文密码，登录时直接字符串比对（不哈希）';
COMMENT ON COLUMN "agent_user".tenant_id IS '主租户ID（登录时优先选中；真实授权以 agent_user_tenant 为准）';
COMMENT ON COLUMN "agent_user".create_at IS '创建时间';
COMMENT ON COLUMN "agent_user".updated_at IS '更新时间（更新时由库触发器刷新）';

CREATE TABLE IF NOT EXISTS agent_user_tenant (
	user_id BIGINT NOT NULL, 
	tenant_id BIGINT NOT NULL, 
	role_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id, tenant_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_aut_super_admin ON agent_user_tenant (role_id) WHERE role_id = 3;

CREATE UNIQUE INDEX IF NOT EXISTS uk_aut_tenant_admin ON agent_user_tenant (tenant_id) WHERE role_id = 5;

COMMENT ON TABLE "agent_user_tenant" IS '用户-租户-角色分配（多对多中间表）';
COMMENT ON COLUMN "agent_user_tenant".user_id IS '用户ID（BigInteger，取自 JWT 的 user_id，不接受请求体传入）';
COMMENT ON COLUMN "agent_user_tenant".tenant_id IS '租户ID（BigInteger，隔离边界，取自 JWT 的 tenant_id）';
COMMENT ON COLUMN "agent_user_tenant".role_id IS '该用户在租户内的唯一角色：1/2 普通用户、3 超管（仅主租户且全局唯一）、5 租户管理员（每租户唯一）';
COMMENT ON COLUMN "agent_user_tenant".created_at IS '分配时间';

-- ============================================================
-- 自动更新 updated_at 触发器
-- 覆盖所有含 updated_at 列的表（表名由模型动态生成）
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'agent',
        'agent_api_call_log',
        'agent_audit_log',
        'agent_capability_policy',
        'agent_config_change_request',
        'agent_config_review',
        'agent_escalation',
        'agent_exam_reviews',
        'agent_exam_submissions',
        'agent_exams',
        'agent_interview_questions',
        'agent_interview_sessions',
        'agent_knowledge_pending_queue',
        'agent_long_term_memory',
        'agent_message',
        'agent_model',
        'agent_model_registry',
        'agent_plugin',
        'agent_qa_sessions',
        'agent_questions',
        'agent_resume_reviews',
        'agent_role',
        'agent_run',
        'agent_scoring_points',
        'agent_tenant',
        'agent_thread',
        'agent_tool',
        'agent_user'
    ]
    LOOP
        EXECUTE format('
            DROP TRIGGER IF EXISTS trg_%I_updated_at ON %I;
            CREATE TRIGGER trg_%I_updated_at
            BEFORE UPDATE ON %I
            FOR EACH ROW
            WHEN (OLD IS DISTINCT FROM NEW)
            EXECUTE FUNCTION update_updated_at_column();
        ', t, t, t, t);
    END LOOP;
END;
$$;

-- ============================================================
-- 默认数据：tenant / user（登录认证主表与租户边界）
-- 只保留主租户与超管账号；密码 123456，明文存储；登录只查 user.username。
-- 超管必须落在 is_primary=true 的租户里，否则判定拿不到超管身份。
-- 其余租户、账号、Agent 目录与开通策略由接口按需创建，脚本不预置。
-- ============================================================

INSERT INTO "agent_tenant" (name, enabled, is_primary) VALUES
('主租户', true, true)
ON CONFLICT (is_primary) WHERE is_primary DO NOTHING;

INSERT INTO "agent_user" (username, name, password, tenant_id) VALUES
('admin', 'admin', '123456', (SELECT id FROM agent_tenant WHERE is_primary))
ON CONFLICT (username) DO NOTHING;

-- 用户-租户-角色：只预置主租户唯一超管；user/tenant 的 id 由序列分配，此处用子查询关联
INSERT INTO agent_user_tenant (user_id, tenant_id, role_id, created_at) VALUES
((SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM agent_tenant WHERE is_primary), 3, now())
ON CONFLICT (user_id, tenant_id) DO NOTHING;


-- ============================================================
-- 默认数据：RBAC 种子（角色 / 权限点 / 用户-租户分配）
-- role_id 为整数业务键：1=student / 2=teacher / 3=admin / 5=tenant_admin
-- 4 已废弃（原 analyst 角色无实际职责，已删除）；编号不重排，避免已有分配数据错位；
-- 角色判定一律按 agent_role.name，代码不读这些数字；
-- 3=admin 只允许出现在主租户（tenant.is_primary=true），全局唯一；
-- 每个租户有且只有一个 5=tenant_admin，只能由超管指定（PUT /admin/tenants/{id}/manager）。
-- scope 格式：资源:动作（资源=agent/基础设施名，动作=create/read/update/delete/upload/download/ask）
-- 幂等可重复执行（ON CONFLICT DO NOTHING）。
-- ============================================================

INSERT INTO agent_role (role_id, name, description, create_at, create_user_id, update_user_id) VALUES
(1, 'student', '学员角色', now(), (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin')),
(2, 'teacher', '教师角色', now(), (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin')),
(3, 'admin', '平台超管（仅主租户，全局唯一）', now(), (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin')),
(5, 'tenant_admin', '租户管理员（每租户一个，由超管指定）', now(), (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin'))
ON CONFLICT (role_id) DO NOTHING;

INSERT INTO agent_role_permission (role_id, scope) VALUES
(1, 'qa:ask'),
(1, 'qa:read'),
(1, 'interview:ask'),
(1, 'interview:read'),
(1, 'resume:ask'),
(1, 'resume:upload'),
(1, 'resume:read'),
(1, 'exam:ask'),
(1, 'exam:read'),
(1, 'knowledge:ask'),
(1, 'knowledge:read'),
(2, 'qa:ask'),
(2, 'qa:read'),
(2, 'interview:ask'),
(2, 'resume:upload'),
(2, 'resume:read'),
(2, 'exam:create'),
(2, 'exam:read'),
(2, 'exam:update'),
(2, 'knowledge:ask'),
(2, 'knowledge:read'),
(2, 'knowledge:upload'),
(2, 'knowledge:download'),
-- 3=平台超管：权限收敛为 agent域 + 登录鉴权域 + 配置中心审核域；不含任何业务域（qa/exam/interview/resume/knowledge）
--   登录鉴权域含 rbac/user/tenant 管理；配置中心审核域含 config/audit 只读
(3, 'agent:read'),
(3, 'agent:write'),
(3, 'agent:create'),
(3, 'agent:delete'),
(3, 'model:read'),
(3, 'model:write'),
(3, 'model:create'),
(3, 'model:delete'),
(3, 'model:update'),
(3, 'auth:login'),
(3, 'auth:read'),
(3, 'auth:write'),
(3, 'rbac:read'),
(3, 'rbac:write'),
(3, 'user:read'),
(3, 'user:write'),
(3, 'user:create'),
(3, 'user:delete'),
(3, 'tenant:read'),
(3, 'tenant:write'),
(3, 'tenant:create'),
(3, 'tenant:delete'),
(3, 'config:read'),
(3, 'config:write'),
(3, 'config:review'),
(3, 'audit:read'),
-- 5=租户管理员：本租户用户与角色 + 本租户审计（读）
-- 不含 config:* / agent:* / model:* / tenant:*：配置中心与 agent 域只归超管
(5, 'qa:read'),
(5, 'audit:read'),
(5, 'rbac:read'),
(5, 'rbac:write')
ON CONFLICT (role_id, scope) DO NOTHING;


-- ============================================================
-- 默认数据：menu（菜单按 scope 下发）
-- scope=NULL 表示登录即可见；
-- /agents /tools /models /config 只授予超管角色，/audit 授予超管与 tenant_admin。
-- 审计日志/配置中心/权限中心下设子菜单；租户管理已移入权限中心。
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS uk_menu_path ON agent_menu (path);

INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('监控概览', '/dashboard', 'DashboardOutlined', 0, 1, true, NULL),
('会话运行', '/sessions', 'MessageOutlined', 0, 2, true, 'qa:read'),
('智能体管理', '/agents', 'RobotOutlined', 0, 3, true, 'agent:read'),
('工具与插件', '/tools', 'ToolOutlined', 0, 4, true, 'agent:write'),
('模型配置', '/models', 'DeploymentUnitOutlined', 0, 5, true, 'model:read'),
('配置中心', '/config', 'SettingOutlined', 0, 6, true, 'config:read'),
('审计日志', '/audit', 'FileSearchOutlined', 0, 7, true, 'audit:read'),
('权限中心', '/rbac', 'SafetyCertificateOutlined', 0, 8, true, 'rbac:read'),
('咨询问答', '/qa', 'CommentOutlined', 0, 9, true, 'qa:read')
ON CONFLICT (path) DO NOTHING;

-- 审计日志：三个审计表的分页查询/过滤（业务审计 / 登录日志 / API 调用日志）
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('业务审计', '/audit/operation', 'FileTextOutlined', (SELECT id FROM agent_menu WHERE path='/audit'), 1, true, 'audit:read'),
('登录日志', '/audit/login', 'LoginOutlined', (SELECT id FROM agent_menu WHERE path='/audit'), 2, true, 'audit:read'),
('调用日志', '/audit/api', 'ApiOutlined', (SELECT id FROM agent_menu WHERE path='/audit'), 3, true, 'audit:read')
ON CONFLICT (path) DO NOTHING;

-- 配置中心：配置申请 / 配置审核
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('配置申请', '/config/request', 'FormOutlined', (SELECT id FROM agent_menu WHERE path='/config'), 1, true, 'config:read'),
('配置审核', '/config/review', 'AuditOutlined', (SELECT id FROM agent_menu WHERE path='/config'), 2, true, 'config:read')
ON CONFLICT (path) DO NOTHING;

-- 权限中心：租户管理（从顶级移入） + 用户管理 + 角色管理 + 菜单管理
INSERT INTO agent_menu (name, path, icon, parent_id, sort_order, visible, scope) VALUES
('租户管理', '/tenants', 'TeamOutlined', (SELECT id FROM agent_menu WHERE path='/rbac'), 1, true, 'tenant:read'),
('用户管理', '/users', 'UserOutlined', (SELECT id FROM agent_menu WHERE path='/rbac'), 2, true, 'rbac:read'),
('角色管理', '/roles', 'KeyOutlined', (SELECT id FROM agent_menu WHERE path='/rbac'), 3, true, 'rbac:read'),
('菜单管理', '/menus', 'MenuOutlined', (SELECT id FROM agent_menu WHERE path='/rbac'), 4, true, 'rbac:read')
ON CONFLICT (path) DO NOTHING;


-- ============================================================
-- 默认数据：agent（Agent 目录，agent_type 与代码注册一致）
-- 仅持久化可展示元数据；build_graph 由代码注册，本表不存图结构。
-- ============================================================

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


-- ============================================================
-- 默认数据：agent_model_registry（模型配置注册表）
-- 4 类默认模型各一条；api_key 留空，由超管在 /models 界面填；
-- 其余字段取当前 .env 默认（LLM_API_BASE / LLM_MODEL 等）。
-- ============================================================

INSERT INTO agent_model_registry (
    model_type, name, provider, base_url, api_key, endpoint_path,
    temperature, timeout_s, max_retries, enabled, sort_order, description,
    create_user_id, update_user_id) VALUES
('llm', 'deepseek-chat', 'openai', 'http://localhost:8000/v1', NULL, NULL,
    0.2, 60, 2, true, 1, '默认 LLM（DeepSeek，经 OpenAI 兼容网关）', (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin')),
('embedding', 'bge-m3', 'local', NULL, NULL, NULL,
    NULL, NULL, NULL, true, 1, 'BGE-M3 向量化（本地 FlagEmbedding）', (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin')),
('reranker', 'bge-reranker-v2-m3', 'local', NULL, NULL, NULL,
    NULL, NULL, NULL, true, 1, 'BGE-Reranker-v2-m3 精排（本地）', (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin')),
('classifier', 'bert-intent-zh', 'local', NULL, NULL, 'models/bert-intent-recognition-model',
    NULL, NULL, NULL, true, 1, '中文意图分类（离线训练产物）', (SELECT id FROM "agent_user" WHERE username='admin'), (SELECT id FROM "agent_user" WHERE username='admin'))
ON CONFLICT (model_type, name) DO NOTHING;
