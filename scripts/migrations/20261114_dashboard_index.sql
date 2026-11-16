-- ============================================================
-- 2026-11-14 看板性能索引
--   · agent_unified_turn(tenant_id, create_at)：看板 token/按天聚合
--   · agent_api_call_log(tenant_id, req_time, status_code)：成功率/错误数覆盖索引
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

CREATE INDEX IF NOT EXISTS ix_unified_turn_tenant_time
  ON agent_unified_turn (tenant_id, create_at);

CREATE INDEX IF NOT EXISTS ix_api_log_tenant_time_status
  ON agent_api_call_log (tenant_id, req_time, status_code);

COMMIT;
