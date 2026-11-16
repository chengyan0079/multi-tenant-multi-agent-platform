-- ============================================================
-- 2026-11-13 新增 agent_db_connection（租户级数据库数据源）
-- 工具（db_metadata / slow_sql 等）按 connection_id 动态连接，不固定绑定。
-- 密码：开发期明文；生产必须改为加密存储。
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

CREATE TABLE IF NOT EXISTS agent_db_connection (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    tenant_id BIGINT NOT NULL,
    name VARCHAR(64) NOT NULL,
    db_type VARCHAR(16) NOT NULL,
    host VARCHAR(255) NOT NULL,
    port INTEGER NOT NULL,
    username VARCHAR(128) NOT NULL,
    password VARCHAR(512) NOT NULL,
    database VARCHAR(128) NOT NULL,
    schema_name VARCHAR(128),
    readonly BOOLEAN DEFAULT true NOT NULL,
    enabled BOOLEAN DEFAULT true NOT NULL,
    remark TEXT,
    create_at TIMESTAMP(0) WITHOUT TIME ZONE DEFAULT date_trunc('second', now()) NOT NULL,
    updated_at TIMESTAMP(0) WITHOUT TIME ZONE DEFAULT date_trunc('second', now()) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_db_conn_tenant_name UNIQUE (tenant_id, name)
);
CREATE INDEX IF NOT EXISTS idx_db_conn_tenant ON agent_db_connection (tenant_id);

COMMENT ON TABLE "agent_db_connection" IS '数据库连接（数据源，租户级）';
COMMENT ON COLUMN "agent_db_connection".password IS '密码（开发期明文；生产必须加密）';

COMMIT;
