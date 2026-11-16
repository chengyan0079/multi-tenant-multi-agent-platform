-- ============================================================
-- 2026-11-13 删除 exam / interview / resume 三个 Agent（保留 qa）
-- 影响范围：
--   · 8 张业务表（DROP）
--   · agent 目录 / agent_capability_policy / agent_model 绑定 / agent_menu / agent_role_permission 的关联数据（DELETE）
-- 说明：
--   · 全库无物理外键，DROP 不会级联报错；仍按「子表 → 父表」顺序执行。
--   · 执行前请备份 agent_platform 库；请确认在 unified_schemas schema 下执行。
--   · 本脚本由人工审核后再执行，未自动运行。
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

-- 1) 模型绑定（表名 agent_model，列 agent_id；必须在 DELETE agent 之前执行）
DELETE FROM agent_model
 WHERE agent_id IN (
     SELECT id FROM agent WHERE agent_type IN ('exam', 'resume', 'interview')
 );

-- 2) 角色权限点（tenant_admin 等角色上的考试/简历/面试权限）
DELETE FROM agent_role_permission
 WHERE scope LIKE 'exam:%'
    OR scope LIKE 'exam_result:%'
    OR scope LIKE 'resume:%'
    OR scope LIKE 'interview:%';

-- 3) 菜单（只删三个助手子树，保留 /agent 父菜单）
DELETE FROM agent_menu
 WHERE path LIKE '/agent/exam%'
    OR path LIKE '/agent/resume%'
    OR path LIKE '/agent/interview%';

-- 4) 租户开通策略
DELETE FROM agent_capability_policy
 WHERE agent_type IN ('exam', 'resume', 'interview');

-- 5) agent 目录（保留 qa）
DELETE FROM agent
 WHERE agent_type IN ('exam', 'resume', 'interview');

-- 6) 业务表（先子表后父表；无物理外键，IF EXISTS 保证可重复执行）
DROP TABLE IF EXISTS agent_exam_reviews;
DROP TABLE IF EXISTS agent_exam_submissions;
DROP TABLE IF EXISTS agent_scoring_points;
DROP TABLE IF EXISTS agent_questions;
DROP TABLE IF EXISTS agent_exams;
DROP TABLE IF EXISTS agent_resume_reviews;
DROP TABLE IF EXISTS agent_interview_sessions;
DROP TABLE IF EXISTS agent_interview_questions;

COMMIT;
