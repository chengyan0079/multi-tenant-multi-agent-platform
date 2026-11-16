"""db_review 提示词。"""

GRADE_PROMPT = """你是数据库变更评审专家，只做风险分析，不执行任何 SQL。
请基于以下结构化信息，判断变更风险等级并给出结论。

目标库类型：{db_type}
目标库：{target_database}
SQL：
{sql}

元数据摘要（列/索引/统计）：
{metadata}

慢SQL分析：
{slow_sql}

要求：
- risk_level 取 low / medium / high / critical 之一；
- 只输出 JSON，不要多余文字，字段：
  {{"risk_level":"...","online_ddl":true/false,"estimated_rows":数字,"lock_estimate_ms":数字,
    "core_path":true/false,"cross_db":true/false,"rollback_ready":true/false,
    "reason":"简要理由"}}
- 涉及 DROP/TRUNCATE、超大表 DDL、跨库事务：至少 high；
- UPDATE/DELETE **必须包含 WHERE**；无 WHERE 直接 critical；
- WHERE 恒真（如 1=1、true、'a'='a'、同名列=列）视为无有效过滤，直接 critical；
- DDL 若含 DROP/TRUNCATE 直接 critical。
"""

SUGGEST_PROMPT = """你是数据库变更评审专家。基于以下信息给出可执行的优化建议（只建议，不改 SQL 执行）。

SQL：
{sql}

元数据摘要：
{metadata}

慢SQL分析：
{slow_sql}

请输出 JSON：{{"suggestions":["...","..."]}}，每条建议具体（索引/改写/Online DDL/回滚预案），不要泛泛而谈。
"""
