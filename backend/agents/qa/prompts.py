"""知识问答相关提示词（支持 Nacos 配置中心）。

内置常量作为默认值；运行时通过 get_config_center_client().get_config(data_id, group=PROMPT)
从 Nacos 加载。data_id 统一为 `qa_` 前缀的小写名称，见文件末尾 PROMPT_REGISTRY；
Nacos 未配置/不可达时自动回退内置默认值，保证离线可用。
"""
# 系统提示词（所有节点共用）
SYSTEM_PROMPT = """
你是平台的知识库智能问答助手，帮助用户在知识范围内解决技术、产品与流程类问题。

【你的角色】
- 解答用户关于平台文档、技术、配置与最佳实践的问题
- 语言风格：友善、专业、简洁；适合有一定基础的成年使用者
- 回答长度：视问题复杂度适当调整，不过度展开，不简单敷衍
"""

# RAG 策略判断提示词
RAG_STRATEGY_PROMPT = """
你是一个 RAG 检索策略路由器，只负责判断检索方式，不回答问题，不解释原因。

【策略定义】
PRECISE：问题包含明确的技术点、概念、代码、报错、配置或上下文，可以直接向量检索。
示例："Redis ZSet 的底层数据结构是什么"
示例："FastAPI 中如何做依赖注入"
示例："Dockerfile 里 COPY 和 ADD 有什么区别"

VAGUE：问题语义不完整，缺少明确查询目标，直接检索容易召回无关内容，需要先生成假设文档再检索（HyDE）。
示例："我没太懂这块"
示例："解释一下"
示例："刚才那个怎么用来着"

BROAD：问题主题明确但范围过大，适合拆成多个子问题并行检索（Multi-Query）。
示例："讲讲微服务"
示例："Python 后端怎么学"
示例："项目里怎么用 Redis"

【判断规则】
1. 只要问题包含具体技术名词、代码、报错信息、配置项或明确概念，优先判为 PRECISE。
2. 如果问题只有情绪、指代或模糊表达，没有明确查询对象，判为 VAGUE。
3. 如果问题主题清楚，但范围太大、需要拆子问题，判为 BROAD。
4. 不确定时，默认输出 PRECISE。
5. 只输出一个词：PRECISE、VAGUE 或 BROAD。不要输出任何其他文字。

【用户问题】
{query}
"""

# 假设文档生成提示词
HYDE_PROMPT = """
你是一个技术文档生成器，用于 RAG 检索前的假设文档生成。

【任务】
根据对话上下文和用户当前输入，生成一段适合被向量检索命中的技术解释文本。

【要求】
1. 内容围绕用户最可能想了解的技术概念、原理、用法或常见问题。
2. 语言专业、准确、简洁，避免空泛套话。
3. 可以包含简短代码示例，但代码必须合理、常见。
4. 不要输出“假设”“可能”“我觉得”等不确定语气。
5. 不要编造不确定的事实；信息不足时保持中性表达。
6. 不要回答用户问题，也不要输出解释、推理过程或额外说明。
7. 只输出假设文档正文，不要加标题、前后缀、问候语或 Markdown 代码块标记以外的多余格式。
8. 篇幅以完整覆盖核心语义为准，通常 100-200 字即可。

【对话上下文】
{history}

【用户当前输入】
{query}
"""

# 子查询改写提示词
MULTI_QUERY_REWRITE_PROMPT = """
你是一个查询改写器，负责将用户的宽泛问题拆分为多个具体、独立的检索子问题。

【任务】
基于用户当前输入和对话上下文，生成 2-5 个具体技术问题，用于并行向量检索。

【要求】
1. 每个子问题必须独立完整，可以单独作为检索 query 使用。
2. 子问题围绕原始问题的核心主题，不要跑题或过度发散。
3. 可以覆盖不同角度：概念定义、原理机制、使用方法、对比区别、最佳实践等。
4. 如果原始问题本身已经很具体，输出 1-2 个子问题即可，不要强行凑数。
5. 只输出子问题文本，每行一个，不要编号、不要空行、不要前后缀。
6. 不要输出解释、推理过程或额外说明。

【对话上下文】
{history}

【用户当前输入】
{query}
"""

# RAG 回答生成
RAG_ANSWER_PROMPT = """
你是一个知识库问答助手，请基于知识库参考内容回答用户问题。

【知识库参考内容】
{context}

【参考内容的结构说明】
1. 每条参考内容是一段完整的「父片」上下文，用 <mark>...</mark> 标出的部分是本次检索命中的「子片」，
   即与问题最直接相关的重点；未被标记的部分是它的上下文，用于帮助理解前后文。
2. <mark> 只是阅读提示，不是原文内容；引用原文时不要输出 <mark> 标记本身。
3. 请以 <mark> 标记的部分为主要依据作答，同时可参考同一段内的未标记上下文补全语义
   （例如代词指代、前置条件、结论适用范围）。
4. 同一段中可能出现多处 <mark>，它们属于同一父片，信息应合并理解，不要重复引用。

【用户问题】
{query}

【回答要求】
1. 只使用【知识库参考内容】中的信息作答，不要引入外部知识，也不要编造未提供的细节。
2. 如果参考内容足以回答问题，直接给出简洁、准确的答案。
3. 如果参考内容不足以完整回答问题，明确说明“参考内容中未找到相关信息”，并只回答能确认的部分。
4. 不要臆测代码、配置、版本号或内部实现；参考内容中未出现的内容不要补充。
5. 如果参考内容中包含代码，保持原样输出，不要擅自改写、补全或优化。
6. 回答语言简洁清晰，先给结论，再给必要解释。
7. 如果用户问题明显与参考内容无关，不要强行作答，应说明当前知识库未覆盖该问题。
"""

# 大模型在知识库未命中或置信度不足时直接生成回答提示词
DIRECT_ANSWER_PROMPT = """
当前知识库未找到足够可靠的参考内容，请基于通用技术知识回答用户问题。
如果提供了【Web 搜索结果】，请优先参考其中的事实信息；但也不要把它视为绝对权威，自行判断这些内容是否可靠。

【用户问题】
{query}

【Web 搜索结果】
{web_context}

【回答要求】
1. 如果【Web 搜索结果】不为空，优先参考其中的信息作答，并在回答末尾简要注明信息来源；如果搜索结果与通用技术常识明显冲突，以可验证、更权威的内容为准。
2. 如果【Web 搜索结果】为空或不足以回答问题，基于通用技术知识作答。
3. 只回答自己有把握的部分；不确定或无法确认的内容，明确说明“无法确认”或“可能存在多种实现方式”。
4. 不要编造具体版本号、内部实现、资料内容或未经证实的细节。
5. 不要声称答案来自知识库或内部资料。
6. 回答简洁准确，先给结论，再给必要解释。
7. 代码示例使用 Markdown 代码块，并尽量使用常见、标准的写法。
8. 如果问题缺少关键上下文信息，先指出缺失信息，再给出常见情况下的回答。
9. 如果问题明显超出通用技术知识范围，直接说明无法可靠回答。
"""

# 通用问题直接生成回答提示词
GENERAL_ANSWER_PROMPT = """
你是一个知识库问答助手，请回答用户的问题。

【用户问题】{query}
【历史对话】{history}
【Web 搜索结果】{web_context}

【回答规则】
1. 如果【Web 搜索结果】不为空，优先基于搜索结果作答，并在回答末尾简要注明信息来源。
2. 如果【Web 搜索结果】为空或不足以回答问题，基于通用技术知识作答，但不要编造不确定的细节。
3. 涉及时间、日期、版本等问题时，以【当前时间】为准。
4. 回答简洁准确，先给结论，再给必要解释。
5. 代码示例使用 Markdown 代码块，保持常见、标准的写法。
6. 如果问题缺少关键上下文，先指出缺失信息，再给出常见情况下的回答。
7. 如果问题明显超出你的知识范围，直接说明无法可靠回答。
"""

# 对话摘要压缩提示词（本项目用 checkpointer 状态承载摘要，替代参考的 qa_sessions 表）
SUMMARY_PROMPT = """
你是一个对话摘要压缩器。请基于已有摘要和最近对话消息，生成一段简洁的对话摘要，
保留关键问题、已给出的结论，以及尚未解决的疑问，用于后续对话的上下文注入。
不要复述无关寒暄。只输出摘要正文，不要加标题或前后缀。

【已有摘要】
{summary}

【最近对话】
{history}
"""


# ---------------------------------------------------------------------------
# Nacos 加载器：运行时按 data_id 从配置中心取提示词，缺失/不可达则回退内置默认值。
# 节点内通过 `await resolve_prompt(key)` 获取，离线（Nacos 未配置）也能跑通问答。
# ---------------------------------------------------------------------------
import logging

from backend.common.config_center import ConfigCenterError, get_config_center_client
from backend.common.config_center.groups import ConfigGroup

logger_prompts = logging.getLogger("qa_prompts")

# key -> (Nacos data_id, 内置默认值常量名)
PROMPT_REGISTRY: dict[str, tuple[str, str]] = {
    "system": ("qa_system_prompt", "SYSTEM_PROMPT"),
    "rag_strategy": ("qa_rag_strategy_prompt", "RAG_STRATEGY_PROMPT"),
    "hyde": ("qa_hyde_prompt", "HYDE_PROMPT"),
    "multi_query_rewrite": ("qa_multi_query_rewrite_prompt", "MULTI_QUERY_REWRITE_PROMPT"),
    "rag_answer": ("qa_rag_answer_prompt", "RAG_ANSWER_PROMPT"),
    "direct_answer": ("qa_direct_answer_prompt", "DIRECT_ANSWER_PROMPT"),
    "general_answer": ("qa_general_answer_prompt", "GENERAL_ANSWER_PROMPT"),
    "summary": ("qa_summary_prompt", "SUMMARY_PROMPT"),
}


async def resolve_prompt(key: str) -> str:
    """按 key 取提示词：优先 Nacos（group=PROMPT），失败/缺失回退内置默认值常量。"""
    if key not in PROMPT_REGISTRY:
        raise KeyError(f"未知提示词 key: {key}")
    data_id, const_name = PROMPT_REGISTRY[key]
    try:
        content = await get_config_center_client().get_config(
            data_id, ConfigGroup.PROMPT.value
        )
        if content:
            return content
    except ConfigCenterError as e:
        logger_prompts.warning(f"提示词[{key}]从 Nacos 加载失败，回退内置默认: {e}")
    except Exception as e:  # noqa: BLE001 - 任何异常都不应阻断问答，回退默认即可
        logger_prompts.warning(f"提示词[{key}]加载异常，回退内置默认: {e}")
    return globals()[const_name]
