-- ============================================================
-- 2026-11-13 平台化：agent 注册租户化 + agent_tool 租户级
-- 影响：
--   C) agent 表加 tenant_id、唯一键改 (tenant_id, agent_type)、DROP agent_capability_policy；
--      enabled 保留为「租户级启停」（每租户行独立控制）
--   B) agent_tool 加 tenant_id + enabled，唯一键改 (tenant_id, name)
-- 说明：
--   · 执行前请备份；请在 unified_schemas schema 下执行。
--   · 存量数据默认归平台租户 tenant_id = 0。
--   · 本脚本由人工审核后再执行，未自动运行。
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

-- ---------------- C: agent 租户化 ----------------
ALTER TABLE agent ADD COLUMN IF NOT EXISTS tenant_id BIGINT NOT NULL DEFAULT 0;
ALTER TABLE agent DROP CONSTRAINT IF EXISTS agent_agent_type_key;
ALTER TABLE agent ADD CONSTRAINT uq_agent_tenant_type UNIQUE (tenant_id, agent_type);
-- enabled 保留：作为租户内启停开关（存量表已有该列，无需新增）

-- 租户开通策略并入 agent 表，原策略表移除
DROP TABLE IF EXISTS agent_capability_policy;

-- ---------------- B: agent_tool 租户级 ----------------
ALTER TABLE agent_tool ADD COLUMN IF NOT EXISTS tenant_id BIGINT NOT NULL DEFAULT 0;
ALTER TABLE agent_tool ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE agent_tool DROP CONSTRAINT IF EXISTS agent_tool_name_key;
ALTER TABLE agent_tool ADD CONSTRAINT uq_agent_tool_tenant_name UNIQUE (tenant_id, name);

COMMIT;
