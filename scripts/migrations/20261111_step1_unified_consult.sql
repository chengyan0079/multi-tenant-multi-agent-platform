-- 2026-11-11 统一咨询入口 Step1：DDL 落地（建统一历史表 / 去会话化 / 删 agent_run）
-- 纯增量、幂等、可重复执行；旧业务数据已清空。
-- 执行：psql -U <管理员> -h <host> -d agent_platform -f scripts/migrations/20261111_step1_unified_consult.sql

BEGIN;

-- 应用表位于 agent_platform schema，脚本未限定 schema，先设置 search_path 以免落到 public
SET search_path TO agent_platform, public;

-- ========== 1) 统一会话历史源（唯一新表） ==========
CREATE TABLE IF NOT EXISTS agent_unified_turn (
    id                 UUID DEFAULT uuid_generate_v4() NOT NULL,
    tenant_id          BIGINT NOT NULL,
    user_id            BIGINT NOT NULL,
    thread_id          UUID NOT NULL,
    trace_id           VARCHAR(64),
    turn_index         INTEGER NOT NULL,
    agent_type         VARCHAR(64) NOT NULL,
    spec_version       VARCHAR(32),
    event_type         VARCHAR(32) NOT NULL,
    user_content       TEXT,
    assistant_content  TEXT,
    payload            JSON,
    routing            JSON,
    status             VARCHAR(16) NOT NULL DEFAULT 'success',
    error_code         VARCHAR(32),
    error_msg          TEXT,
    latency_ms         INTEGER,
    token_usage        JSON,
    create_at          TIMESTAMP(0) WITHOUT TIME ZONE DEFAULT date_trunc('second', now()) NOT NULL,
    updated_at         TIMESTAMP(0) WITHOUT TIME ZONE DEFAULT date_trunc('second', now()) NOT NULL,
    create_user_id     BIGINT NOT NULL,
    update_user_id     BIGINT NOT NULL,
    create_tenant_id   BIGINT,
    update_tenant_id   BIGINT,
    PRIMARY KEY (id),
    CONSTRAINT uq_unified_turn_thread_index UNIQUE (thread_id, turn_index)
);

CREATE INDEX IF NOT EXISTS ix_agent_unified_turn_tenant_id ON agent_unified_turn (tenant_id);
CREATE INDEX IF NOT EXISTS ix_agent_unified_turn_thread_id ON agent_unified_turn (thread_id);
CREATE INDEX IF NOT EXISTS ix_agent_unified_turn_user_id ON agent_unified_turn (user_id);
CREATE INDEX IF NOT EXISTS ix_unified_turn_agent ON agent_unified_turn (tenant_id, agent_type, create_at);
CREATE INDEX IF NOT EXISTS ix_unified_turn_owner ON agent_unified_turn (tenant_id, user_id, thread_id, turn_index);
CREATE INDEX IF NOT EXISTS ix_unified_turn_trace ON agent_unified_turn (trace_id);

COMMENT ON TABLE agent_unified_turn IS '统一会话历史（唯一会话历史源）';
COMMENT ON COLUMN agent_unified_turn.id IS 'turn_id（主键 UUID）';
COMMENT ON COLUMN agent_unified_turn.tenant_id IS '租户ID（隔离边界，BigInteger）';
COMMENT ON COLUMN agent_unified_turn.user_id IS '用户ID（user_id，BigInteger）';
COMMENT ON COLUMN agent_unified_turn.thread_id IS '关联 agent_thread.id（=U）';
COMMENT ON COLUMN agent_unified_turn.trace_id IS '链路追踪ID';
COMMENT ON COLUMN agent_unified_turn.turn_index IS '会话内轮次序号（单调递增）';
COMMENT ON COLUMN agent_unified_turn.agent_type IS 'Agent 类型（由 spec 动态取值）';
COMMENT ON COLUMN agent_unified_turn.spec_version IS 'spec 版本';
COMMENT ON COLUMN agent_unified_turn.event_type IS '事件类型';
COMMENT ON COLUMN agent_unified_turn.user_content IS '用户输入';
COMMENT ON COLUMN agent_unified_turn.assistant_content IS '助手输出';
COMMENT ON COLUMN agent_unified_turn.payload IS '事件负载 + artifact_type/artifact_id';
COMMENT ON COLUMN agent_unified_turn.routing IS '路由决策快照';
COMMENT ON COLUMN agent_unified_turn.status IS '轮次态（success/stopped/failed）';
COMMENT ON COLUMN agent_unified_turn.error_code IS '错误码';
COMMENT ON COLUMN agent_unified_turn.error_msg IS '错误信息';
COMMENT ON COLUMN agent_unified_turn.latency_ms IS '端到端耗时（毫秒）';
COMMENT ON COLUMN agent_unified_turn.token_usage IS 'Token 用量（JSON）';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_agent_unified_turn_updated_at') THEN
        EXECUTE format(
            'CREATE TRIGGER trg_agent_unified_turn_updated_at
             BEFORE UPDATE ON agent_unified_turn
             FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();'
        );
    END IF;
END $$;

-- ========== 2) agent_thread：删 graph_name 列 + 重命名唯一约束 ==========
ALTER TABLE agent_thread DROP CONSTRAINT IF EXISTS uq_agent_thread_tenant_user_graph_session;
ALTER TABLE agent_thread ADD CONSTRAINT uq_agent_thread_tenant_user_session UNIQUE (tenant_id, user_id, session_key);
ALTER TABLE agent_thread DROP COLUMN IF EXISTS graph_name;

-- ========== 3) 业务表去会话化 + 加 turn_id（可空，待 Step6/7 统一层回填后收紧 NOT NULL） ==========
-- qa_results
ALTER TABLE agent_qa_results DROP COLUMN IF EXISTS session_id;
ALTER TABLE agent_qa_results DROP COLUMN IF EXISTS thread_id;
ALTER TABLE agent_qa_results ADD COLUMN IF NOT EXISTS turn_id UUID;
CREATE INDEX IF NOT EXISTS ix_agent_qa_results_turn_id ON agent_qa_results (turn_id);
-- interview_sessions
ALTER TABLE agent_interview_sessions DROP COLUMN IF EXISTS session_id;
ALTER TABLE agent_interview_sessions DROP COLUMN IF EXISTS thread_id;
ALTER TABLE agent_interview_sessions DROP COLUMN IF EXISTS summary;
ALTER TABLE agent_interview_sessions DROP CONSTRAINT IF EXISTS uq_interview_sessions_thread;
ALTER TABLE agent_interview_sessions ADD COLUMN IF NOT EXISTS turn_id UUID;
CREATE INDEX IF NOT EXISTS ix_agent_interview_sessions_turn_id ON agent_interview_sessions (turn_id);
-- exam_submissions
ALTER TABLE agent_exam_submissions ADD COLUMN IF NOT EXISTS turn_id UUID;
CREATE INDEX IF NOT EXISTS ix_agent_exam_submissions_turn_id ON agent_exam_submissions (turn_id);
-- resume_reviews
ALTER TABLE agent_resume_reviews ADD COLUMN IF NOT EXISTS turn_id UUID;
CREATE INDEX IF NOT EXISTS ix_agent_resume_reviews_turn_id ON agent_resume_reviews (turn_id);

-- ========== 4) 删 agent_run 表（零写入链路，看板已用 API 日志兜底） ==========
DROP TABLE IF EXISTS agent_run;

COMMIT;
