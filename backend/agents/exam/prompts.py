"""试卷批阅提示词：支持 Nacos 配置中心热更新，缺失回退内置默认值；评分前强制 CoT 对齐 rubric 并产出可解释依据。"""

SYSTEM_PROMPT = """
你是一位严谨、公正的 IT 课程助教，负责协助教师批改学员试卷。

【批改原则】
- 严格按照得分点评分，不随意加减分
- 给出明确的得分依据，指出学员答案中的具体内容
- 评语简洁专业，指出核心问题，避免空泛表扬或批评
- 对有争议的内容保持保守评分，宁可偏低并标记复核，不随意给高分
"""

# 主观题思考提示词
# 先生成逐得分点核对的分析文字，再把分析结果拼到评分提示词后面
SUBJECTIVE_THINK_PROMPT = """
在批改这道简答题之前，请先进行深入分析。

【题目】
{question_content}

【标准得分点】
{scoring_points}

【学员作答】
{student_answer}

请分析以下几点（中文，5-8句话）：
1. 学员是否理解了题目的核心概念？
2. 逐一检查每个得分点：学员的回答是否覆盖了该要点？是否用不同表述但实质正确？
3. 有没有表述模糊但实质正确、不应扣分的内容？
4. 有没有明显的概念错误或理解偏差？

直接输出分析内容，不加任何前缀标签。
"""

# 主观题评分提示词
SUBJECTIVE_REVIEW_PROMPT = """
请按照以下得分点批改学员的简答题作答。

【题目】
{question_content}

【得分点（共{full_score}分）】
{scoring_points}

【学员答案】
{student_answer}

请严格按照得分点逐条评分，输出以下 JSON 结构（直接输出，不要加 Markdown 代码块）：
{{
  "question_id": "",
  "student_answer": "{student_answer}",
  "total_score": <整数，各得分点累加>,
  "full_score": {full_score},
  "confidence": <0.0-1.0，评分把握度，不确定时给低分并降低 confidence>,
  "point_results": [
    {{
      "point_id": "<得分点ID，若无则填空字符串>",
      "point_desc": "<得分点描述>",
      "point_score": <该得分点满分>,
      "earned": <true/false>,
      "evidence": "<学员答案中对应的原文，earned=true 时必填>",
      "missing": "<未得分的原因，earned=false 时必填>"
    }}
  ],
  "overall_comment": "<1-2句整体评语，指出最核心的问题或亮点>"
}}
"""

# 代码题评分提示词
# 先判断功能是否正确，再评估代码质量，综合给分
CODE_REVIEW_PROMPT = """
请评估以下代码题的学员提交代码：先判断是否正确实现了题目要求的功能，再评估代码质量，综合给分。

【题目要求】
{question}

【参考实现（标准答案，用于对照学员代码是否正确）】
{reference_solution}

【学员代码】
{code}

【评分参考】（总分 {full_score} 分）
- {full_score}分：功能完全正确 + 代码规范 + 边界处理完善
- {full_score}×0.8分：功能完全正确，但代码风格/命名/注释有瑕疵
- {full_score}×0.6分：功能基本正确，有少量边界情况未处理
- {full_score}×0.4分：功能部分实现，核心逻辑有误或缺失
- 0分：未提交 / 代码无法运行 / 完全未实现题目要求

输出 JSON 结构（直接输出，不要加 Markdown 代码块）
{{
  "score": <整数，0到{full_score}>,
  "confidence": <0到1之间的小数，表示你对本次评分的把握；越不确定填得越低>,
  "feedback": [
    "<功能正确性：是否正确实现题目要求（最重要）>",
    "<代码规范性：缩进/括号/命名等>",
    "<算法效率：时间/空间复杂度>",
    "<边界与异常处理>",
    "<可读性与注释>"
  ]
}}
"""

# 薄弱点分析提示词
# 把失分题清单交给大模型，归纳知识点并生成复习建议
WEAK_POINTS_ANALYSIS_PROMPT = """
你是一位经验丰富的 IT 课程教师，请根据学员本次试卷的答题情况，分析其知识薄弱点并给出复习建议。

【错题/扣分题清单】
{wrong_questions}

【说明】
- 上方列出了本次试卷中学员答错或扣分的题目，包含题目内容和错误原因
- 请将这些题目归纳到对应的知识点，分析薄弱原因，并给出具体的复习建议

请输出以下 JSON 结构（直接输出，不要加 Markdown 代码块）：
{{
  "weak_points": [
    {{
      "tag": "<知识点名称，例如：Spring IOC、Redis缓存穿透、JVM垃圾回收>",
      "wrong_count": <该知识点下的错题数>,
      "total_count": <该知识点下的总题数，若不确定填与wrong_count相同>,
      "question_nos": [<题目序号列表>],
      "suggestion": "<针对该知识点的具体复习建议，1-2句>"
    }}
  ],
  "overall_summary": "<对学员本次考试整体表现的简短评价，指出最核心的1-2个薄弱方向，不超过50字>"
}}
"""


# ---------------------------------------------------------------------------
# Nacos 加载器：运行时按 data_id 从配置中心取提示词，缺失/不可达则回退内置默认值。
# 节点内通过 `await resolve_prompt(key)` 获取，离线（Nacos 未配置）也能跑通批阅。
# ---------------------------------------------------------------------------
import logging

from backend.common.config_center import ConfigCenterError, get_config_center_client
from backend.common.config_center.groups import ConfigGroup

logger_prompts = logging.getLogger("exam_prompts")

# key -> (Nacos data_id, 内置默认值常量名)
PROMPT_REGISTRY: dict[str, tuple[str, str]] = {
    "system": ("exam_system_prompt", "SYSTEM_PROMPT"),
    "subjective_think": ("exam_subjective_think_prompt", "SUBJECTIVE_THINK_PROMPT"),
    "subjective_review": ("exam_subjective_review_prompt", "SUBJECTIVE_REVIEW_PROMPT"),
    "code_review": ("exam_code_review_prompt", "CODE_REVIEW_PROMPT"),
    "weak_points_analysis": (
        "exam_weak_points_analysis_prompt",
        "WEAK_POINTS_ANALYSIS_PROMPT",
    ),
}


async def resolve_prompt(key: str) -> str:
    """按 key 取提示词：优先 Nacos（group=PROMPT），失败/缺失回退内置默认值常量。"""
    if key not in PROMPT_REGISTRY:
        raise KeyError(f"未知提示词 key: {key}")
    data_id, const_name = PROMPT_REGISTRY[key]
    try:
        content = await get_config_center_client().get_config(data_id, ConfigGroup.PROMPT.value)
        if content:
            return content
    except ConfigCenterError as e:
        logger_prompts.warning(f"提示词[{key}]从 Nacos 加载失败，回退内置默认: {e}")
    except Exception as e:  # noqa: BLE001 - 任何异常都不应阻断批阅，回退默认即可
        logger_prompts.warning(f"提示词[{key}]加载异常，回退内置默认: {e}")
    return globals()[const_name]
