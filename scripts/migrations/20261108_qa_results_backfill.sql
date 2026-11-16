-- 回填旧 QA 结果：sources 空数组用检索上下文补齐；token_usage/extra 填可解释的占位。
-- 历史 LLM token 无法真实恢复，usage_available=false 标明不是实际为 0。
UPDATE agent_platform.agent_qa_results AS r
SET
    sources = CASE
        WHEN r.sources IS NULL OR r.sources::text IN ('[]', 'null') THEN
            COALESCE(
                (
                    SELECT json_agg(s.label)
                    FROM (
                        SELECT DISTINCT '历史低相关候选：' || (ctx.value->>'source') AS label
                        FROM json_array_elements(r.retrieved_contexts) AS ctx(value)
                        WHERE COALESCE(ctx.value->>'source', '') <> ''
                    ) s
                ),
                '["模型内置知识（无外部引用）"]'::json
            )
        ELSE r.sources
    END,
    token_usage = COALESCE(
        r.token_usage,
        json_build_object(
            'prompt_tokens', 0,
            'completion_tokens', 0,
            'total_tokens', 0,
            'llm_calls', 0,
            'models', '[]'::json,
            'usage_available', false,
            'reason', '历史记录未采集 LLM usage，数值不代表真实消耗'
        )
    ),
    extra = COALESCE(
        r.extra,
        json_build_object(
            'backfilled', true,
            'reason', 'LLM usage 回调接入前产生的历史记录',
            'answer_mode', r.answer_mode,
            'query_type', r.query_type,
            'context_count', (
                SELECT count(*) FROM json_array_elements(r.retrieved_contexts)
            ),
            'usage_available', false
        )
    )
WHERE
    r.sources IS NULL
    OR r.sources::text IN ('[]', 'null')
    OR r.token_usage IS NULL
    OR r.extra IS NULL;
