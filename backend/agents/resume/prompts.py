"""
prompts - 简历评审相关提示词（迁移到 Nacos 配置中心）

每个提示词都有内置默认值（下方常量），运行时通过 get_config_center_client().get_config(data_id, group=PROMPT)
从 Nacos 按 data_id 加载；Nacos 未配置/不可达时自动回退到内置默认值（保证离线可用）。
Nacos 中建议的 data_id 见文件末尾 PROMPT_REGISTRY（组固定为 PROMPT）。
"""
# 基础系统提示词
# SYSTEM_PROMPT = (
#     '你是一位经验丰富的 IT 行业职业顾问，专门为应届毕业生和初/中级工程师审查简历。\n'
#     '你的评审严格、客观、可操作，不给出模糊的夸奖，只给出具体的问题定位和修改建议。'
# )
#
# # 结构化提取提示词
# EXTRACT_STRUCTURED_PROMPT = '''
# 请从以下简历文本中提取结构化信息。
# 【简历原文】
# {resume_text}
#
# 提取要求：
# - 完整保留项目描述的原始文字，不要改写或压缩
# - 技术栈列表每项单独一个（如 Spring Boot、MySQL，不合并）
# - 时间格式统一为 yyyy.MM - yyyy.MM（如写"至今"则保留"至今"）
# - 无法提取的字段填空字符串，不要填"未知"或"无"
# - 量化亮点：只提取含数字的句子（如"提升30%"、"10万DAU"）
# '''
#
# # 项目深度评审提示词
# PROJECT_DEPTH_PROMPT = '''
# 请评审以下简历在【项目深度】维度的表现。
# 【评审重点】
# {focus}
#
# 【结构化摘要】
# {structured_summary}
#
# 评分标准（0-100分）：
# - 90-100：每个项目都有量化指标、明确的技术选型理由、清晰的个人贡献和难点解决
# - 70-89： 大部分项目有量化数据，个人贡献基本清晰
# - 50-69： 项目描述偏泛，缺少量化数据，个人贡献不明确
# - 30-49： 项目描述流水账，看不出技术深度
# - 0-29：  项目描述极度简陋或与岗位完全不相关
# '''
#
# # 技术匹配度评审提示词
# TECH_MATCH_PROMPT = '''
# 请评审以下简历在【技术匹配度】维度的表现。
# 【评审重点】
# {focus}
#
# 【结构化摘要】
# {structured_summary}
#
# 评分标准（0-100分）：
# - 90-100：技术栈与目标岗位高度匹配，有明确掌握程度分级
# - 70-89： 主要技术匹配，技能描述基本清晰
# - 50-69： 技术栈部分匹配，技能描述缺乏层次
# - 30-49： 技术栈与目标岗位匹配度低，或罗列过多不相关技术
# - 0-29：  几乎无相关技术经验
# '''
#
# # 表达规范性评审提示词
# EXPRESSION_PROMPT = '''
# 请评审以下简历在【表达规范性】维度的表现。
# 【评审重点】
# {focus}
#
# 【结构化摘要】
# {structured_summary}
#
# 评分标准（0-100分）：
# - 90-100：所有条目动词开头，逻辑清晰，无错别字，无歧义
# - 70-89： 大部分条目规范，偶有主语省略但不影响理解
# - 50-69： 部分条目表述不清，有明显的主语歧义或格式问题
# - 30-49： 大量表达问题，影响阅读体验
# - 0-29：  表达混乱，难以理解
# '''
#
# # 简历结构评审提示词
# STRUCTURED_PROMPT = '''
# 请评审以下简历在【简历结构】维度的表现。
# 【评审重点】
# {focus}
#
# 【结构化摘要】
# {structured_summary}
#
# 评分标准（0-100分）：
# - 90-100：模块齐全，重要内容置顶，信息密度合理，一眼抓住亮点
# - 70-89： 结构基本合理，略有排版瑕疵
# - 50-69： 模块顺序不合理或有重要模块缺失
# - 30-49： 结构混乱，重要信息被埋没
# - 0-29：  无清晰结构
# '''
#
# # 成果量化程度评审提示词
# QUANTIFICATION_PROMPT = '''
# 请评审以下简历在【量化程度】维度的表现。
# 【评审重点】
# {focus}
#
# 【结构化摘要】
# {structured_summary}
#
# 评分标准（0-100分）：
# - 90-100：绝大多数项目/工作描述有具体数字（QPS/DAU/优化比例/服务规模）
# - 70-89： 部分有量化数据，覆盖主要项目
# - 50-69： 少量量化数据，大部分描述为定性表述
# - 30-49： 几乎无量化数据
# - 0-29：  完全无量化数据
# '''
#
# # 描述一致性评审提示词
# AUTHENTICITY_PROMPT = '''
# 请评审以下简历在【描述一致性】维度的表现。
# 【评审重点】
# {focus}
#
# 【结构化摘要】
# {structured_summary}
#
# 评分标准（0-100分），依据技术描述与经验年限的内在一致性打分：
# - 90-100：技术深度与工作年限高度吻合，项目复杂度与经验阶段匹配，时间线清晰连贯
# - 70-89： 整体一致，个别描述略显笼统，但不影响对候选人水平的判断
# - 50-69： 项目描述与经验阶段存在明显落差，或时间线衔接不清晰
# - 30-49： 多处技术描述与经验年限不符，项目职责描述模糊或缺乏细节
# - 0-29：  描述极度空洞或前后矛盾，无法评估候选人实际水平
# '''
#
# # 六维度评审提示词合集
# DIMENSION_REVIEW_PROMPTS = {
#     '项目深度': PROJECT_DEPTH_PROMPT,
#     '技术匹配度': TECH_MATCH_PROMPT,
#     '表达规范性': EXPRESSION_PROMPT,
#     '简历结构': STRUCTURED_PROMPT,
#     '量化程度': QUANTIFICATION_PROMPT,
#     '真实可信度': AUTHENTICITY_PROMPT,
# }
#
# # 诊断前思考提示词
# DIAGNOSE_THINK_PROMPT = '''
# 在生成简历问题诊断清单之前，请先进行宏观分析。
# 【六维度评分汇总】
# {dimension_scores_summary}
#
# 【已识别的原始问题列表】
# {raw_issues}
#
# 请分析以下几点（中文，5-8句话）：
# 1. 这份简历最核心的短板是什么？（最多2个，直接影响竞争力）
# 2. 各维度问题之间是否存在共同模式或根本原因？
# 3. 声称的技能与实际项目经历描述之间是否存在明显落差？
# 4. 哪些问题最影响面试官的第一印象，应列为高优先级？
#
# 直接输出分析内容，不加任何前缀标签。
# '''
#
# # 问题诊断提示词
# DIAGNOSE_ISSUES_PROMPT = '''
# 请基于以下信息，生成简历的逐条问题诊断清单。
# 【结构化摘要】
# {structured_summary}
#
# 【简历原文】
# {resume_text}
#
# 【各维度已发现问题（可以补充）】
# {raw_issues}
#
# 输出要求：
# 1. 每条问题必须定位到简历的具体位置（如"项目经历-电商系统-第2句"）
# 2. 优先级判断标准：
#    - high：严重影响 HR 通过率，如：无量化数据/项目描述空洞/关键技术缺失
#    - medium：影响竞争力，如：表达不规范/技能描述层次不清
#    - low：锦上添花，如：证书未列出/格式细节
# 3. 时间线推理规则（避免误判）：
#    - 项目时间落在某段工作经历区间内，视为该公司的工作项目，属于正常，不得标记为矛盾
#    - 只有当项目时间与所有工作经历区间均无交集时，才提示候选人补充项目来源说明（low 优先级）
#    - 多个项目与同一段工作经历时间重叠，同样正常，不构成矛盾
# 4. 建议必须具体可操作（给出修改示例或明确指导）
# 5. 去除重复问题，合并相似问题
# 6. 总数控制在 5-15 条
# '''
#
# # 整体评价提示词
# GENERATE_SUMMARY_PROMPT = '''
# 请为学员生成简历审查的整体评价报告。
# 【学员信息摘要】
# {structured_summary}
#
# 【各维度评分】
# {scores_summary}
#
# 【综合得分】
# {weighted_score} / 100
#
# 【高优先级问题（最需解决的）】
# {high_issues}
#
# 【目标岗位】
# {target_position}
#
# 生成要求：
# 1. 亮点：找出简历中真实存在的2-3个优势（有数据支撑更好），语气积极正面
# 2. 核心改进：提炼最重要的2-3个改进方向（优先级 high 的问题），具体指出是哪方面
# 3. 综合评语：1-2句话，客观评价整体水平，不要过度夸奖也不要打击
# 4. 匹配度：基于技术栈和经历，评估与{target_position}岗位的匹配程度（1句话）
# '''

# ---------------------------------------------------------------------------
# Nacos 加载器：运行时按 data_id 从配置中心取提示词，缺失/不可达则回退内置默认值。
# 节点内通过 `await resolve_prompt(key)` 获取，离线（Nacos 未配置）也能跑通评审。
# ---------------------------------------------------------------------------
import logging

from backend.common.config_center import ConfigCenterError, get_config_center_client
from backend.common.config_center.groups import ConfigGroup

logger_prompts = logging.getLogger("resume_prompts")

# key -> (Nacos data_id, 内置默认值常量名)
PROMPT_REGISTRY: dict[str, tuple[str, str]] = {
    "system": ("resume_system_prompt", "SYSTEM_PROMPT"),
    "extract_structured": ("resume_extract_structured_prompt", "EXTRACT_STRUCTURED_PROMPT"),
    "dim:项目深度": ("resume_project_depth_prompt", "PROJECT_DEPTH_PROMPT"),
    "dim:技术匹配度": ("resume_tech_match_prompt", "TECH_MATCH_PROMPT"),
    "dim:表达规范性": ("resume_expression_prompt", "EXPRESSION_PROMPT"),
    "dim:简历结构": ("resume_structured_prompt", "STRUCTURED_PROMPT"),
    "dim:量化程度": ("resume_quantification_prompt", "QUANTIFICATION_PROMPT"),
    "dim:真实可信度": ("resume_authenticity_prompt", "AUTHENTICITY_PROMPT"),
    "diagnose_think": ("resume_diagnose_think_prompt", "DIAGNOSE_THINK_PROMPT"),
    "diagnose_issues": ("resume_diagnose_issues_prompt", "DIAGNOSE_ISSUES_PROMPT"),
    "generate_summary": ("resume_generate_summary_prompt", "GENERATE_SUMMARY_PROMPT"),
}


async def resolve_prompt(key: str) -> str:
    """按 key 取提示词：优先 Nacos，失败/缺失回退内置默认值常量。"""
    if key not in PROMPT_REGISTRY:
        raise KeyError(f"未知提示词 key: {key}")
    data_id, const_name = PROMPT_REGISTRY[key]
    try:
        content = await get_config_center_client().get_config(data_id, ConfigGroup.PROMPT.value)
        if content:
            return content
    except ConfigCenterError as e:
        logger_prompts.warning(f"提示词[{key}]从 Nacos 加载失败，回退内置默认: {e}")
    except Exception as e:  # noqa: BLE001 - 任何异常都不应阻断评审，回退默认即可
        logger_prompts.warning(f"提示词[{key}]加载异常，回退内置默认: {e}")
    return globals()[const_name]


async def resolve_dimension_prompt(dim_name: str) -> str:
    """按维度名（中文，如 '项目深度'）取对应评审提示词。"""
    return await resolve_prompt(f"dim:{dim_name}")
