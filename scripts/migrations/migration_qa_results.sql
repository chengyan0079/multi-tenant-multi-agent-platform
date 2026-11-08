-- ============================================================
-- 问答结果 / RAGAS 评估 建表迁移（作用于已有库；幂等可重复执行）
-- 表：
--   agent_qa_results      一次问答一行（原始输入输出 + 追溯信息，RAGAS 样本源）
--   agent_qa_ragas_evals  一次评估一行（可对同一问答多次评估，保留历史）
-- 用法： psql -U <用户> -h <host> -d <db> -f scripts/migration_qa_results.sql
-- ============================================================

SET search_path TO agent_platform;

BEGIN;

-- 1) 问答结果主表
CREATE TABLE IF NOT EXISTS agent_qa_results (
	id UUID DEFAULT uuid_generate_v4() NOT NULL,
	trace_id VARCHAR(64),
	tenant_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	session_id VARCHAR(128) NOT NULL,
	thread_id UUID,
	agent_type VARCHAR(32) NOT NULL,
	question TEXT NOT NULL,
	answer TEXT,
	answer_mode VARCHAR(32),
	query_type VARCHAR(32),
	confidence NUMERIC(5, 4),
	retrieved_contexts JSON,
	sources JSON,
	reference_answer TEXT,
	latency_ms INTEGER,
	token_usage JSON,
	enable_web_search BOOLEAN NOT NULL,
	status VARCHAR(16) NOT NULL,
	error_msg TEXT,
	extra JSON,
	create_at TIMESTAMP(0) WITHOUT TIME ZONE DEFAULT date_trunc('second', now()) NOT NULL,
	updated_at TIMESTAMP(0) WITHOUT TIME ZONE DEFAULT date_trunc('second', now()) NOT NULL,
	create_user_id BIGINT NOT NULL,
	update_user_id BIGINT NOT NULL,
	create_tenant_id BIGINT,
	update_tenant_id BIGINT,
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_qa_results_tenant_time ON agent_qa_results (tenant_id, create_at);
CREATE INDEX IF NOT EXISTS idx_qa_results_user_time ON agent_qa_results (user_id, create_at);
CREATE INDEX IF NOT EXISTS idx_qa_results_session ON agent_qa_results (session_id);
CREATE INDEX IF NOT EXISTS idx_qa_results_thread ON agent_qa_results (thread_id);
CREATE INDEX IF NOT EXISTS idx_qa_results_trace ON agent_qa_results (trace_id);
CREATE INDEX IF NOT EXISTS idx_qa_results_status ON agent_qa_results (status);

COMMENT ON TABLE "agent_qa_results" IS '问答结果（一次问答一行，供 RAGAS 质量验证）';
COMMENT ON COLUMN "agent_qa_results".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_qa_results".trace_id IS '链路追踪ID（与 agent_api_call_log.trace_id 对齐，可关联）';
COMMENT ON COLUMN "agent_qa_results".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_qa_results".user_id IS '提问用户ID（user_id，BigInteger）';
COMMENT ON COLUMN "agent_qa_results".session_id IS '会话标识（qa 的 session_id / agent_thread.session_key）';
COMMENT ON COLUMN "agent_qa_results".thread_id IS '关联 agent_thread.id（会话）';
COMMENT ON COLUMN "agent_qa_results".agent_type IS '智能体类型（默认 qa）';
COMMENT ON COLUMN "agent_qa_results".question IS '用户问题（RAGAS user_input）';
COMMENT ON COLUMN "agent_qa_results".answer IS '模型回答（RAGAS response）';
COMMENT ON COLUMN "agent_qa_results".answer_mode IS '回答模式（rag/llm_direct/general/fallback）';
COMMENT ON COLUMN "agent_qa_results".query_type IS '查询类型（如 PRECISE/BROAD）';
COMMENT ON COLUMN "agent_qa_results".confidence IS '置信度（0-1）';
COMMENT ON COLUMN "agent_qa_results".retrieved_contexts IS '检索上下文（JSON 数组：content/doc_id/score，RAGAS retrieved_contexts）';
COMMENT ON COLUMN "agent_qa_results".sources IS '引用来源（JSON，展示用）';
COMMENT ON COLUMN "agent_qa_results".reference_answer IS '参考答案（RAGAS reference；人工标注或知识库标准答案，可空）';
COMMENT ON COLUMN "agent_qa_results".latency_ms IS '端到端耗时（毫秒）';
COMMENT ON COLUMN "agent_qa_results".token_usage IS 'Token 用量（JSON：prompt/completion/total）';
COMMENT ON COLUMN "agent_qa_results".enable_web_search IS '是否启用联网检索';
COMMENT ON COLUMN "agent_qa_results".status IS '执行结果（success/failed/partial）';
COMMENT ON COLUMN "agent_qa_results".error_msg IS '失败原因';
COMMENT ON COLUMN "agent_qa_results".extra IS '扩展信息（JSON：模型名/图版本/实验标记等）';
COMMENT ON COLUMN "agent_qa_results".create_at IS '创建时间';
COMMENT ON COLUMN "agent_qa_results".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_qa_results".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_qa_results".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_qa_results".create_tenant_id IS '创建租户ID（写 SQL 时注入）；超管不挂租户，其操作记 NULL';
COMMENT ON COLUMN "agent_qa_results".update_tenant_id IS '更新租户ID（写 SQL 时注入）；超管不挂租户，其操作记 NULL';

-- 2) RAGAS 评估结果表
CREATE TABLE IF NOT EXISTS agent_qa_ragas_evals (
	id UUID DEFAULT uuid_generate_v4() NOT NULL,
	qa_result_id UUID NOT NULL,
	trace_id VARCHAR(64),
	tenant_id BIGINT NOT NULL,
	evaluator VARCHAR(64) NOT NULL,
	evaluator_model VARCHAR(128),
	dataset_version VARCHAR(64),
	faithfulness NUMERIC(6, 4),
	answer_relevancy NUMERIC(6, 4),
	context_precision NUMERIC(6, 4),
	context_recall NUMERIC(6, 4),
	answer_correctness NUMERIC(6, 4),
	metrics JSON,
	status VARCHAR(16) NOT NULL,
	error_msg TEXT,
	eval_at TIMESTAMP(0) WITHOUT TIME ZONE,
	create_at TIMESTAMP(0) WITHOUT TIME ZONE DEFAULT date_trunc('second', now()) NOT NULL,
	updated_at TIMESTAMP(0) WITHOUT TIME ZONE DEFAULT date_trunc('second', now()) NOT NULL,
	create_user_id BIGINT NOT NULL,
	update_user_id BIGINT NOT NULL,
	create_tenant_id BIGINT,
	update_tenant_id BIGINT,
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_qa_ragas_qa_result ON agent_qa_ragas_evals (qa_result_id);
CREATE INDEX IF NOT EXISTS idx_qa_ragas_tenant_time ON agent_qa_ragas_evals (tenant_id, eval_at);
CREATE INDEX IF NOT EXISTS idx_qa_ragas_trace ON agent_qa_ragas_evals (trace_id);
CREATE INDEX IF NOT EXISTS idx_qa_ragas_status ON agent_qa_ragas_evals (status);

COMMENT ON TABLE "agent_qa_ragas_evals" IS 'RAGAS 评估结果（一次评估一行，支持多次评估留痕）';
COMMENT ON COLUMN "agent_qa_ragas_evals".id IS '主键（UUID）';
COMMENT ON COLUMN "agent_qa_ragas_evals".qa_result_id IS '关联 agent_qa_results.id';
COMMENT ON COLUMN "agent_qa_ragas_evals".trace_id IS '链路追踪ID';
COMMENT ON COLUMN "agent_qa_ragas_evals".tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN "agent_qa_ragas_evals".evaluator IS '评估器（ragas）';
COMMENT ON COLUMN "agent_qa_ragas_evals".evaluator_model IS '评估模型（LLM/embedding 名称与版本）';
COMMENT ON COLUMN "agent_qa_ragas_evals".dataset_version IS '数据集/标注版本';
COMMENT ON COLUMN "agent_qa_ragas_evals".faithfulness IS '忠实度（回答是否被上下文支持）';
COMMENT ON COLUMN "agent_qa_ragas_evals".answer_relevancy IS '答案相关性';
COMMENT ON COLUMN "agent_qa_ragas_evals".context_precision IS '上下文精确率';
COMMENT ON COLUMN "agent_qa_ragas_evals".context_recall IS '上下文召回率';
COMMENT ON COLUMN "agent_qa_ragas_evals".answer_correctness IS '答案正确性';
COMMENT ON COLUMN "agent_qa_ragas_evals".metrics IS '全量指标（JSON，含自定义/新增指标，避免频繁改表）';
COMMENT ON COLUMN "agent_qa_ragas_evals".status IS '评估状态（pending/running/success/failed）';
COMMENT ON COLUMN "agent_qa_ragas_evals".error_msg IS '失败原因';
COMMENT ON COLUMN "agent_qa_ragas_evals".eval_at IS '评估时间';
COMMENT ON COLUMN "agent_qa_ragas_evals".create_at IS '创建时间';
COMMENT ON COLUMN "agent_qa_ragas_evals".updated_at IS '更新时间（更新时由库触发器刷新）';
COMMENT ON COLUMN "agent_qa_ragas_evals".create_user_id IS '创建人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_qa_ragas_evals".update_user_id IS '更新人ID（写 SQL 时注入）';
COMMENT ON COLUMN "agent_qa_ragas_evals".create_tenant_id IS '创建租户ID（写 SQL 时注入）；超管不挂租户，其操作记 NULL';
COMMENT ON COLUMN "agent_qa_ragas_evals".update_tenant_id IS '更新租户ID（写 SQL 时注入）；超管不挂租户，其操作记 NULL';

COMMIT;
