-- 迁移：统一咨询收口后，原各智能体的「发起/独立会话」入口已下掉后端接口，
-- 对应菜单项应同步移除；成果查看页（问答结果/文件列表/简历分析/考试结果/面试结果）
-- 仍是统一咨询的结果跳转目标，予以保留。
--
-- 用法（存量库增量升级）：
--   psql -U <用户> -h <host> -d <db> -f scripts/migrations/20261112_remove_agent_entry_menus.sql

DELETE FROM agent_menu
WHERE path IN (
    '/agent/qa/chat',          -- QA问答（发起入口）
    '/agent/qa/sessions',      -- 会话列表（独立会话，统一咨询会话在 /consultation/sessions）
    '/agent/exam/start',       -- 开始考试（发起入口）
    '/agent/interview/start'   -- 开始面试（发起入口）
);
