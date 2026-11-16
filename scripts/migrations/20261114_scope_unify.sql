-- ============================================================
-- 2026-11-14 权限点收敛：QA_* → UNIFIED_*
--   qa:ask       → unified:ask（合并去重）
--   qa:result:*  → unified_result:*（page/view/review）
--   qa:menu      → 删除（菜单改用 unified:ask）
--   qa_session:* → 删除（会话已用 unified_session:*）
-- 保留：qa_file:*（知识库文档上传/下载/列表仍在用）
-- ============================================================
SET search_path TO unified_schemas;
BEGIN;

-- 1) 角色权限：qa:ask → unified:ask（先补后删，避免丢权限）
INSERT INTO agent_role_permission (role_id, scope)
SELECT DISTINCT role_id, 'unified:ask'
  FROM agent_role_permission
 WHERE scope = 'qa:ask'
ON CONFLICT (role_id, scope) DO NOTHING;

-- 2) 角色权限：qa:result:* → unified_result:*
INSERT INTO agent_role_permission (role_id, scope)
SELECT DISTINCT role_id,
       'unified_result:' || split_part(scope, ':', 2)
  FROM agent_role_permission
 WHERE scope LIKE 'qa_result:%'
ON CONFLICT (role_id, scope) DO NOTHING;

-- 3) 清理旧权限点
DELETE FROM agent_role_permission
 WHERE scope IN ('qa:ask', 'qa:menu')
    OR scope LIKE 'qa_result:%'
    OR scope LIKE 'qa_session:%';

-- 4) 菜单：问答助手入口改用 unified:ask
UPDATE agent_menu SET scope = 'unified:ask' WHERE path = '/agent/qa';

COMMIT;

-- 5) 校验（执行后查看）
SELECT scope, count(*) AS roles
  FROM agent_role_permission
 WHERE scope LIKE 'qa%' OR scope LIKE 'unified%'
 GROUP BY scope
 ORDER BY scope;
