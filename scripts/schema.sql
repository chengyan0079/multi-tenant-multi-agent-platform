-- ============================================================
-- agent-platform 元数据表（PostgreSQL）
-- 本脚本为设计稿 SQL，结构与 RAG-Ultra 对齐；配置中心审批流与 API 调用日志两张系统表复用其结构。
-- 说明：列默认值由 ORM 在写入时提供（Python 侧 default），故 DDL 不含服务器端 DEFAULT；
--       自增主键用 BIGSERIAL/SERIAL，JSON 列用 JSONB，时间列用 TIMESTAMP（无时区）。
-- ============================================================


-- ==========================================================
-- 1) 核心表（核心会话/运行/轨迹/插件/工具/记忆/审计，均带 tenant_id 做租户隔离）
-- ==========================================================

CREATE TABLE agent_thread (
  id VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  graph_name VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  PRIMARY KEY (id)
);
COMMENT ON TABLE agent_thread IS '会话/任务';
COMMENT ON COLUMN agent_thread.id IS '主键';
COMMENT ON COLUMN agent_thread.tenant_id IS '租户ID';
COMMENT ON COLUMN agent_thread.status IS '状态（active/...）';
COMMENT ON COLUMN agent_thread.graph_name IS '关联图名';
COMMENT ON COLUMN agent_thread.created_at IS '创建时间';
COMMENT ON COLUMN agent_thread.updated_at IS '更新时间';
CREATE INDEX ix_agent_thread_tenant_id ON agent_thread (tenant_id);

CREATE TABLE agent_run (
  id VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  thread_id VARCHAR(64) NOT NULL,
  graph_name VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  prompt_tokens INT NOT NULL,
  completion_tokens INT NOT NULL,
  cost_cents INT NOT NULL,
  started_at TIMESTAMP NOT NULL,
  ended_at TIMESTAMP,
  PRIMARY KEY (id)
);
COMMENT ON TABLE agent_run IS '运行台账（token/成本/延迟）';
COMMENT ON COLUMN agent_run.id IS '主键';
COMMENT ON COLUMN agent_run.tenant_id IS '租户ID';
COMMENT ON COLUMN agent_run.thread_id IS '会话ID';
COMMENT ON COLUMN agent_run.graph_name IS '图名';
COMMENT ON COLUMN agent_run.status IS '状态（running/done/...）';
COMMENT ON COLUMN agent_run.prompt_tokens IS '提示token数';
COMMENT ON COLUMN agent_run.completion_tokens IS '补全token数';
COMMENT ON COLUMN agent_run.cost_cents IS '成本（分）';
COMMENT ON COLUMN agent_run.started_at IS '开始时间';
COMMENT ON COLUMN agent_run.ended_at IS '结束时间';
CREATE INDEX ix_agent_run_tenant_id ON agent_run (tenant_id);
CREATE INDEX ix_agent_run_thread_id ON agent_run (thread_id);

CREATE TABLE agent_message (
  id VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  thread_id VARCHAR(64) NOT NULL,
  run_id VARCHAR(64) NOT NULL,
  role VARCHAR(32) NOT NULL,
  type VARCHAR(32) NOT NULL,
  payload TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  PRIMARY KEY (id)
);
COMMENT ON TABLE agent_message IS 'append-only 轨迹（replay/fork）';
COMMENT ON COLUMN agent_message.id IS '主键';
COMMENT ON COLUMN agent_message.tenant_id IS '租户ID';
COMMENT ON COLUMN agent_message.thread_id IS '会话ID';
COMMENT ON COLUMN agent_message.run_id IS '运行ID';
COMMENT ON COLUMN agent_message.role IS '角色';
COMMENT ON COLUMN agent_message.type IS '类型';
COMMENT ON COLUMN agent_message.payload IS '负载（JSON）';
COMMENT ON COLUMN agent_message.created_at IS '创建时间';
CREATE INDEX ix_agent_message_tenant_id ON agent_message (tenant_id);
CREATE INDEX ix_agent_message_thread_id ON agent_message (thread_id);

CREATE TABLE agent_plugin (
  name VARCHAR(64) NOT NULL,
  version VARCHAR(32) NOT NULL,
  capabilities TEXT NOT NULL,
  status VARCHAR(32) NOT NULL,
  config TEXT NOT NULL,
  registered_at TIMESTAMP NOT NULL,
  PRIMARY KEY (name)
);
COMMENT ON TABLE agent_plugin IS '能力/插件注册表（持久化视角）';
COMMENT ON COLUMN agent_plugin.name IS '插件名（主键）';
COMMENT ON COLUMN agent_plugin.version IS '版本';
COMMENT ON COLUMN agent_plugin.capabilities IS '能力列表（JSON）';
COMMENT ON COLUMN agent_plugin.status IS '状态（enabled/...）';
COMMENT ON COLUMN agent_plugin.config IS '配置（JSON）';
COMMENT ON COLUMN agent_plugin.registered_at IS '注册时间';

CREATE TABLE agent_tool (
  name VARCHAR(64) NOT NULL,
  plugin VARCHAR(64) NOT NULL,
  description TEXT NOT NULL,
  schema TEXT NOT NULL,
  PRIMARY KEY (name)
);
COMMENT ON TABLE agent_tool IS '工具目录';
COMMENT ON COLUMN agent_tool.name IS '工具名（主键）';
COMMENT ON COLUMN agent_tool.plugin IS '所属插件';
COMMENT ON COLUMN agent_tool.description IS '描述';
COMMENT ON COLUMN agent_tool.schema IS 'JSON Schema';

CREATE TABLE agent_escalation (
  id VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  thread_id VARCHAR(64) NOT NULL,
  reason VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL,
  assigned_to VARCHAR(64) NOT NULL,
  resolved_at TIMESTAMP,
  PRIMARY KEY (id)
);
COMMENT ON TABLE agent_escalation IS 'HITL / 转人工队列';
COMMENT ON COLUMN agent_escalation.id IS '主键';
COMMENT ON COLUMN agent_escalation.tenant_id IS '租户ID';
COMMENT ON COLUMN agent_escalation.thread_id IS '会话ID';
COMMENT ON COLUMN agent_escalation.reason IS '原因';
COMMENT ON COLUMN agent_escalation.status IS '状态（pending/resolved）';
COMMENT ON COLUMN agent_escalation.assigned_to IS '处理人';
COMMENT ON COLUMN agent_escalation.resolved_at IS '解决时间';
CREATE INDEX ix_agent_escalation_tenant_id ON agent_escalation (tenant_id);
CREATE INDEX ix_agent_escalation_thread_id ON agent_escalation (thread_id);

CREATE TABLE agent_long_term_memory (
  id VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  agent_id VARCHAR(64) NOT NULL,
  block VARCHAR(32) NOT NULL,
  content TEXT NOT NULL,
  embedding_id VARCHAR(64) NOT NULL,
  PRIMARY KEY (id)
);
COMMENT ON TABLE agent_long_term_memory IS '长期记忆（分页块）';
COMMENT ON COLUMN agent_long_term_memory.id IS '主键';
COMMENT ON COLUMN agent_long_term_memory.tenant_id IS '租户ID';
COMMENT ON COLUMN agent_long_term_memory.agent_id IS 'AgentID';
COMMENT ON COLUMN agent_long_term_memory.block IS '块类型（人设/事实/偏好/摘要）';
COMMENT ON COLUMN agent_long_term_memory.content IS '内容';
COMMENT ON COLUMN agent_long_term_memory.embedding_id IS '向量ID';
CREATE INDEX ix_agent_long_term_memory_tenant_id ON agent_long_term_memory (tenant_id);

CREATE TABLE agent_audit_log (
  id VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  actor VARCHAR(64) NOT NULL,
  action VARCHAR(64) NOT NULL,
  target VARCHAR(128) NOT NULL,
  detail TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  PRIMARY KEY (id)
);
COMMENT ON TABLE agent_audit_log IS '审计日志';
COMMENT ON COLUMN agent_audit_log.id IS '主键';
COMMENT ON COLUMN agent_audit_log.tenant_id IS '租户ID';
COMMENT ON COLUMN agent_audit_log.actor IS '操作人';
COMMENT ON COLUMN agent_audit_log.action IS '动作';
COMMENT ON COLUMN agent_audit_log.target IS '目标';
COMMENT ON COLUMN agent_audit_log.detail IS '详情（JSON）';
COMMENT ON COLUMN agent_audit_log.created_at IS '创建时间';
CREATE INDEX ix_agent_audit_log_tenant_id ON agent_audit_log (tenant_id);


-- ==========================================================
-- 2) 业务元数据表（按 EduAgent 规范，每 Agent 独立建表，tenant_id 隔离）
-- ==========================================================

CREATE TABLE biz_resume_record (
  id VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  file_ref VARCHAR(128) NOT NULL,
  scores TEXT NOT NULL,
  report TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  PRIMARY KEY (id)
);
COMMENT ON TABLE biz_resume_record IS '简历审查结果';
COMMENT ON COLUMN biz_resume_record.id IS '主键';
COMMENT ON COLUMN biz_resume_record.tenant_id IS '租户ID';
COMMENT ON COLUMN biz_resume_record.file_ref IS '文件引用';
COMMENT ON COLUMN biz_resume_record.scores IS '六维度评分（JSON）';
COMMENT ON COLUMN biz_resume_record.report IS '报告';
COMMENT ON COLUMN biz_resume_record.created_at IS '创建时间';
CREATE INDEX ix_biz_resume_record_tenant_id ON biz_resume_record (tenant_id);

CREATE TABLE biz_exam_record (
  id VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  file_ref VARCHAR(128) NOT NULL,
  summary TEXT NOT NULL,
  published BOOLEAN NOT NULL,
  created_at TIMESTAMP NOT NULL,
  PRIMARY KEY (id)
);
COMMENT ON TABLE biz_exam_record IS '试卷批改结果';
COMMENT ON COLUMN biz_exam_record.id IS '主键';
COMMENT ON COLUMN biz_exam_record.tenant_id IS '租户ID';
COMMENT ON COLUMN biz_exam_record.file_ref IS '文件引用';
COMMENT ON COLUMN biz_exam_record.summary IS '判分摘要';
COMMENT ON COLUMN biz_exam_record.published IS '是否发布';
COMMENT ON COLUMN biz_exam_record.created_at IS '创建时间';
CREATE INDEX ix_biz_exam_record_tenant_id ON biz_exam_record (tenant_id);

CREATE TABLE biz_interview_record (
  id VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  session_id VARCHAR(64) NOT NULL,
  report TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  PRIMARY KEY (id)
);
COMMENT ON TABLE biz_interview_record IS '面试报告';
COMMENT ON COLUMN biz_interview_record.id IS '主键';
COMMENT ON COLUMN biz_interview_record.tenant_id IS '租户ID';
COMMENT ON COLUMN biz_interview_record.session_id IS '面试会话ID';
COMMENT ON COLUMN biz_interview_record.report IS '报告';
COMMENT ON COLUMN biz_interview_record.created_at IS '创建时间';
CREATE INDEX ix_biz_interview_record_tenant_id ON biz_interview_record (tenant_id);


-- ==========================================================
-- 3) 系统级表（无 tenant_id）：配置中心审批流 + API 调用日志（复用 RAG-Ultra 结构）
-- ==========================================================

CREATE TABLE agent_config_change_request (
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
  applicant VARCHAR(64),
  reviewer VARCHAR(64),
  reason VARCHAR(512),
  nacos_history_nid BIGINT,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  PRIMARY KEY (id)
);
COMMENT ON TABLE agent_config_change_request IS '配置变更申请';
COMMENT ON COLUMN agent_config_change_request.id IS '主键';
COMMENT ON COLUMN agent_config_change_request.namespace IS 'Nacos 命名空间';
COMMENT ON COLUMN agent_config_change_request.group_id IS 'Nacos 分组';
COMMENT ON COLUMN agent_config_change_request.data_id IS 'Nacos 配置ID';
COMMENT ON COLUMN agent_config_change_request.domain IS '业务域（如 prompt）';
COMMENT ON COLUMN agent_config_change_request.op_type IS '操作类型（1=新增 2=修改 3=删除 4=回滚）';
COMMENT ON COLUMN agent_config_change_request.title IS '标题';
COMMENT ON COLUMN agent_config_change_request.content_new IS '拟下发内容（全文，审批前未进 Nacos）';
COMMENT ON COLUMN agent_config_change_request.old_config_id IS '变更前 Nacos config_info.id（CAS 基准引用）';
COMMENT ON COLUMN agent_config_change_request.old_config_md5 IS '申请时 Nacos 当前 md5（CAS 基准）';
COMMENT ON COLUMN agent_config_change_request.old_history_nid IS '执行后回填：变更前内容归档历史 nid';
COMMENT ON COLUMN agent_config_change_request.content_format IS '内容格式（json/text/yaml）';
COMMENT ON COLUMN agent_config_change_request.src_history_nid IS '回滚来源历史 nid';
COMMENT ON COLUMN agent_config_change_request.status IS '状态（0=待复核 1=通过 2=驳回 3=已执行）';
COMMENT ON COLUMN agent_config_change_request.applicant IS '申请人';
COMMENT ON COLUMN agent_config_change_request.reviewer IS '复核人';
COMMENT ON COLUMN agent_config_change_request.reason IS '变更原因';
COMMENT ON COLUMN agent_config_change_request.nacos_history_nid IS '执行后回填：新内容历史 nid';
COMMENT ON COLUMN agent_config_change_request.created_at IS '创建时间';
COMMENT ON COLUMN agent_config_change_request.updated_at IS '更新时间';
CREATE INDEX idx_status ON agent_config_change_request (status);
CREATE INDEX idx_domain ON agent_config_change_request (domain);
CREATE INDEX idx_data ON agent_config_change_request (namespace, group_id, data_id);

CREATE TABLE agent_config_review (
  id BIGSERIAL NOT NULL,
  request_id BIGINT NOT NULL,
  reviewer VARCHAR(64),
  action SMALLINT NOT NULL,
  comment VARCHAR(512),
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  PRIMARY KEY (id)
);
COMMENT ON TABLE agent_config_review IS '配置复核记录';
COMMENT ON COLUMN agent_config_review.id IS '主键';
COMMENT ON COLUMN agent_config_review.request_id IS '关联申请ID';
COMMENT ON COLUMN agent_config_review.reviewer IS '复核人';
COMMENT ON COLUMN agent_config_review.action IS '动作（1=通过 2=驳回）';
COMMENT ON COLUMN agent_config_review.comment IS '复核意见';
COMMENT ON COLUMN agent_config_review.created_at IS '创建时间';
COMMENT ON COLUMN agent_config_review.updated_at IS '更新时间';
CREATE INDEX idx_request ON agent_config_review (request_id);

CREATE TABLE agent_api_call_log (
  id BIGSERIAL NOT NULL,
  trace_id VARCHAR(64),
  caller VARCHAR(128),
  user_id VARCHAR(64),
  tenant_id VARCHAR(64),
  method VARCHAR(16) NOT NULL,
  path VARCHAR(512) NOT NULL,
  route VARCHAR(512),
  query_string VARCHAR(1024),
  req_headers JSONB,
  req_body TEXT,
  req_time TIMESTAMP NOT NULL,
  status_code INT,
  resp_body TEXT,
  resp_time TIMESTAMP,
  cost_ms INT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  PRIMARY KEY (id)
);
COMMENT ON TABLE agent_api_call_log IS 'API 调用日志（一条请求一行：请求侧 + 响应侧 + 耗时）';
COMMENT ON COLUMN agent_api_call_log.id IS '主键';
COMMENT ON COLUMN agent_api_call_log.trace_id IS '链路追踪ID（X-Trace-Id）';
COMMENT ON COLUMN agent_api_call_log.caller IS '调用方（X-Forwarded-For 首段 / client host）';
COMMENT ON COLUMN agent_api_call_log.user_id IS '用户ID（X-User-Id，网关下发）';
COMMENT ON COLUMN agent_api_call_log.tenant_id IS '租户ID（X-Tenant-Id，可为空）';
COMMENT ON COLUMN agent_api_call_log.method IS 'HTTP 方法（GET/POST/...）';
COMMENT ON COLUMN agent_api_call_log.path IS '请求路径（不含 query）';
COMMENT ON COLUMN agent_api_call_log.route IS '匹配路由模板（如 /admin/files/{oss_key}）';
COMMENT ON COLUMN agent_api_call_log.query_string IS '查询字符串';
COMMENT ON COLUMN agent_api_call_log.req_headers IS '请求头（JSON；敏感头已脱敏）';
COMMENT ON COLUMN agent_api_call_log.req_body IS '请求体（POST 记 JSON；multipart/超长不记录）';
COMMENT ON COLUMN agent_api_call_log.req_time IS '请求时间';
COMMENT ON COLUMN agent_api_call_log.status_code IS 'HTTP 状态码';
COMMENT ON COLUMN agent_api_call_log.resp_body IS '响应体（JSON；超长截断）';
COMMENT ON COLUMN agent_api_call_log.resp_time IS '响应时间';
COMMENT ON COLUMN agent_api_call_log.cost_ms IS '耗时（毫秒）';
COMMENT ON COLUMN agent_api_call_log.created_at IS '创建时间';
CREATE INDEX idx_path_time ON agent_api_call_log (path, req_time);
CREATE INDEX idx_req_time ON agent_api_call_log (req_time);
CREATE INDEX idx_trace ON agent_api_call_log (trace_id);


-- ==========================================================
-- 4) RBAC：用户/租户/角色三者关系与权限（约束：一用户在单租户只任一角色）
-- ==========================================================

CREATE TABLE agent_role (
  role_id VARCHAR(64) NOT NULL,
  name VARCHAR(64) NOT NULL,
  description TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  PRIMARY KEY (role_id)
);
COMMENT ON TABLE agent_role IS '角色目录（全局：student/teacher/admin）';
COMMENT ON COLUMN agent_role.role_id IS '角色ID';
COMMENT ON COLUMN agent_role.name IS '角色展示名';
COMMENT ON COLUMN agent_role.description IS '角色说明';
COMMENT ON COLUMN agent_role.created_at IS '创建时间';

CREATE TABLE agent_role_permission (
  role_id VARCHAR(64) NOT NULL,
  scope VARCHAR(128) NOT NULL,
  PRIMARY KEY (role_id, scope),
  CONSTRAINT fk_role_perm_role FOREIGN KEY (role_id) REFERENCES agent_role (role_id)
);
COMMENT ON TABLE agent_role_permission IS '角色→scope 权限映射（qa:chat/exam:grade/* 等）';
COMMENT ON COLUMN agent_role_permission.role_id IS '角色ID';
COMMENT ON COLUMN agent_role_permission.scope IS '权限点（最小粒度）';

CREATE TABLE agent_user_tenant (
  user_id VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  role_id VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL,
  PRIMARY KEY (user_id, tenant_id),
  CONSTRAINT fk_ut_role FOREIGN KEY (role_id) REFERENCES agent_role (role_id)
);
COMMENT ON TABLE agent_user_tenant IS '用户-租户-角色分配；PK=(user_id,tenant_id) 强制单租户内只任一角色';
COMMENT ON COLUMN agent_user_tenant.user_id IS '用户ID（上游网关断言）';
COMMENT ON COLUMN agent_user_tenant.tenant_id IS '租户ID（隔离边界）';
COMMENT ON COLUMN agent_user_tenant.role_id IS '该用户在租户内的唯一角色';
COMMENT ON COLUMN agent_user_tenant.created_at IS '分配时间';
CREATE INDEX idx_ut_tenant ON agent_user_tenant (tenant_id);
CREATE INDEX idx_ut_role ON agent_user_tenant (role_id);

