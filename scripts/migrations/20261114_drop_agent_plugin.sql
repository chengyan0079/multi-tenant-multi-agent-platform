-- ============================================================
-- 2026-11-14 统一到 agent_tool：删除重复表 agent_plugin
-- 说明：工具类型/租户/启停/配置全部由 agent_tool 维护。
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

DROP TABLE IF EXISTS agent_plugin;

COMMIT;
