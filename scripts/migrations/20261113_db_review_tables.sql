-- ============================================================
-- 2026-11-13 db_review 业务表：变更单 + 评审结果
-- 执行前请备份；search_path=unified_schemas。
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

CREATE TABLE IF NOT EXISTS agent_change_request (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    thread_id VARCHAR(64) NOT NULL,
    turn_id VARCHAR(64) DEFAULT '',
    title VARCHAR(200) DEFAULT '',
    target_database VARCHAR(128) NOT NULL,
    db_type VARCHAR(16) NOT NULL,
    connection_id VARCHAR(64) NOT NULL,
    sql_text TEXT NOT NULL,
    script_file_id BIGINT,
    drill_file_id BIGINT,
    risk_level VARCHAR(16),
    status VARCHAR(24) DEFAULT 'draft' NOT NULL,
    trace_id VARCHAR(64),
    create_at TIMESTAMP(0) WITHOUT TIME ZONE DEFAULT date_trunc('second', now()) NOT NULL,
    updated_at TIMESTAMP(0) WITHOUT TIME ZONE DEFAULT date_trunc('second', now()) NOT NULL,
    create_user_id BIGINT,
    update_user_id BIGINT,
    create_tenant_id BIGINT,
    update_tenant_id BIGINT
);
CREATE INDEX IF NOT EXISTS idx_change_req_tenant ON agent_change_request (tenant_id);
CREATE INDEX IF NOT EXISTS idx_change_req_thread ON agent_change_request (thread_id);

CREATE TABLE IF NOT EXISTS agent_change_review (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    request_id BIGINT NOT NULL,
    risk_level VARCHAR(16),
    online_ddl BOOLEAN,
    estimated_rows BIGINT,
    lock_estimate_ms INTEGER,
    core_path BOOLEAN,
    cross_db BOOLEAN,
    rollback_ready BOOLEAN,
    slow_sql JSONB,
    suggestions JSONB,
    metadata_snapshot JSONB,
    detail JSONB,
    status VARCHAR(16) DEFAULT 'done' NOT NULL,
    create_at TIMESTAMP(0) WITHOUT TIME ZONE DEFAULT date_trunc('second', now()) NOT NULL,
    updated_at TIMESTAMP(0) WITHOUT TIME ZONE DEFAULT date_trunc('second', now()) NOT NULL,
    create_user_id BIGINT,
    update_user_id BIGINT,
    create_tenant_id BIGINT,
    update_tenant_id BIGINT
);
CREATE INDEX IF NOT EXISTS idx_change_review_tenant ON agent_change_review (tenant_id);
CREATE INDEX IF NOT EXISTS idx_change_review_request ON agent_change_review (request_id);

COMMENT ON TABLE "agent_change_request" IS '数据库变更单（db_review）';
COMMENT ON TABLE "agent_change_review" IS '数据库变更评审结果（db_review）';

COMMIT;
