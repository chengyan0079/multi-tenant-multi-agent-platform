"""问答节点：意图分类/HyDE/Multi-Query/检索/生成/Web 兜底/记忆，基础设施映射 LLMFactory 与 rag.retrieval。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from typing import List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from backend.agents.qa.prompts import resolve_prompt
from backend.agents.qa.state import QAState, RankedChunk, WebSearchResult
from backend.app_state import app_state
from backend.common.llm.llm_factory import get_llm
from backend.common.logger import get_logger
from backend.config import config
from backend.rag.ranked import Chunk
from backend.rag.retrieval import retrieve as retrieve_chunks

logger = get_logger("qa_nodes")

# 本项目无独立 GENERAL agent，所有生成类节点统一用 qa 模型配置
QA_AGENT_TYPE = "qa"
NO_EXTERNAL_SOURCE = "模型内置知识（无外部引用）"
MAX_SOURCE_REFS = 8


def _chunk_source(chunk: Any) -> str:
    """兼容 RankedChunk 对象 / dict，取展示用来源。"""
    if isinstance(chunk, dict):
        return str(chunk.get("source") or chunk.get("metadata", {}).get("source_location") or "")
    return str(
        getattr(chunk, "source", "")
        or getattr(chunk, "metadata", {}).get("source_location", "")
        or ""
    )


def _retrieved_source_refs(state: QAState, *, limit: int = MAX_SOURCE_REFS) -> list[str]:
    """低置信度直答时，把检索候选来源保留到 sources，避免结果表只有上下文没有来源。"""
    refs: list[str] = []
    for chunk in state.get("ranked_chunks") or []:
        source = _chunk_source(chunk).strip()
        if not source:
            continue
        label = f"低相关候选：{source}"
        if label not in refs:
            refs.append(label)
        if len(refs) >= limit:
            break
    return refs


# 检索/精排阈值与窗口参数已外置到 config.qa（见 backend/config/schemas.py QaSettings），可通过 .env 的 QA_* 覆盖

_WEEKDAYS_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


# --------------------------------------------------------------------------- #
# 公共工具
# --------------------------------------------------------------------------- #
def _current_datetime_str() -> str:
    """返回格式化的当前时间字符串，供注入 System 提示词。"""
    now = datetime.now()
    return now.strftime(f"%Y年%m月%d日 {_WEEKDAYS_CN[now.weekday()]} %H:%M")


async def _build_full_system_prompt(
    summary: Optional[str] = None, need_time_info: bool = True
) -> str:
    """构建注入了当前时间与历史摘要的 System 内容，供所有生成节点共用。

    注意：历史摘要必须定期更新且有过期策略；切勿把完整历史消息直接塞进系统提示词，
    否则会破坏大模型的角色边界。
    """
    content = await resolve_prompt("system")
    if need_time_info:
        content += f"\n\n【当前时间】{_current_datetime_str()}"
    if summary:
        content += f"\n\n【历史摘要】\n{summary}"
    return content


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数：CJK 按 ~1 token/字，其余按 ~4 字符/token（中文为主场景够用）。"""
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    return cjk + max(other // 4, 0) + 1


def _window(messages: List, max_tokens: int = 2000) -> List:
    """取消息列表末尾、在 token 预算内的窗口，避免长对话溢出上下文或丢失关键历史。

    从最新消息向前累加，超出预算即截断（保留最近、最重要的上下文）。
    """
    out: List = []
    used = 0
    for m in reversed(messages):
        content = m.content if hasattr(m, "content") else str(m)
        text = content if isinstance(content, str) else str(content)
        t = _estimate_tokens(text)
        if out and used + t > max_tokens:
            break
        out.append(m)
        used += t
    return list(reversed(out))


def _dedup_key(text: str) -> str:
    """用全文内容哈希做去重 key，避免按前 N 字符切片导致的误合并/漏合并。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _should_summarize(messages: List) -> bool:
    """按用户提问轮数判断是否触发摘要压缩（阈值来自 config.qa.summary_trigger_turns）。"""
    human_turns = sum(1 for m in messages if isinstance(m, HumanMessage))
    return human_turns >= config.qa.summary_trigger_turns


# --------------------------------------------------------------------------- #
# 意图识别辅助（规则 + LLM 策略 + 分类器软提示）
# --------------------------------------------------------------------------- #
_WEB_SEARCH_HINTS = (
    "联网",
    "联网查询",
    "联网搜索",
    "上网查",
    "上网搜",
    "网上搜",
    "搜索一下",
    "可以搜索",
    "帮我搜",
    "百度一下",
    "谷歌一下",
)


def _extract_query_and_web_flag(raw_query: str) -> tuple[str, bool]:
    """检测用户消息是否含联网请求指令，返回（清洗后的 query, 是否要求联网）。"""
    import re

    needs_web = any(h in raw_query for h in _WEB_SEARCH_HINTS)
    if not needs_web:
        return raw_query, False
    clean_query = re.sub(
        r"[，,。.？?！!\s]*(?:如果不知道|不知道的话|不清楚|你可以)?"
        r"\s*(?:可以)?\s*(?:联网|上网|网上)?(?:查询|搜索|搜一下|查一查|百度|谷歌).*$",
        "",
        raw_query,
    ).strip()
    return (clean_query or raw_query), True


_GENERAL_EXACT = {
    "你好",
    "hi",
    "hello",
    "嗨",
    "hey",
    "谢谢",
    "谢谢你",
    "感谢",
    "thanks",
    "thank you",
    "你是谁",
    "你叫什么",
    "你叫什么名字",
    "你是什么",
    "你能做什么",
    "你有什么功能",
    "你能帮我做什么",
    "再见",
    "拜拜",
    "bye",
}

_GENERAL_KEYWORDS = {
    "你是谁",
    "你叫什么",
    "你能做什么",
    "你有什么功能",
    "介绍一下你自己",
    "自我介绍",
    "今天天气",
    "天气怎么样",
    "讲个笑话",
    "说个故事",
    "今天是",
    "今天几号",
    "今天是几号",
    "今天是星期",
    "现在是",
    "现在几点",
    "现在时间",
    "当前时间",
    "当前日期",
    "几月几号",
    "星期几",
    "是几月",
    "几号了",
    "日期是",
    "今天日期",
}


def _rule_classify_general(query: str) -> bool:
    """规则层：闲聊 / 问时间 / 打招呼等。"""
    q = query.strip().lower()
    if q in _GENERAL_EXACT:
        return True
    return any(kw in q for kw in _GENERAL_KEYWORDS)


_SPECIALIZED_KEYWORDS = {
    "文档",
    "资料",
    "手册",
    "案例",
    "规范",
    "接口",
    "字段",
    "报错",
    "日志",
    "配置",
    "部署",
    "项目",
    "实操",
}


def _rule_classify_specialized(query: str) -> bool:
    """规则层：含知识库相关信号词，走 RAG 策略判定。"""
    q = query.lower()
    return any(kw in q for kw in _SPECIALIZED_KEYWORDS)


_VAGUE_QUERY_HINTS = {"没懂", "不懂", "不太懂", "讲讲", "解释一下", "啥意思", "什么意思", "看不懂"}
_BROAD_QUERY_HINTS = {"全面", "系统", "总结", "梳理", "路线", "对比", "区别", "全景", "有哪些"}


def _fast_rag_strategy(query: str) -> str:
    """规则快判 RAG 策略。"""
    q = query.strip().lower()
    if len(q) <= 6 and any(kw in q for kw in _VAGUE_QUERY_HINTS):
        return "VAGUE"
    if any(kw in q for kw in _BROAD_QUERY_HINTS):
        return "BROAD"
    return "PRECISE"


async def _determine_rag_strategy(query: str) -> str:
    """LLM 精判 RAG 策略（仅在规则判为 VAGUE/BROAD 且问题较长时调用）。"""
    try:
        prompt = ChatPromptTemplate.from_template(await resolve_prompt("rag_strategy"))
        llm = await get_llm(QA_AGENT_TYPE)
        chain = prompt | llm | StrOutputParser()
        result = (await chain.ainvoke({"query": query})).strip()
        if result in ("PRECISE", "VAGUE", "BROAD"):
            return result
    except Exception as e:  # noqa: BLE001 - 模型判定失败应降级而非中断
        logger.exception(f"classify.rag_strategy_failed | {e}")
    return "PRECISE"


async def _determine_rag_strategy_fast(query: str) -> str:
    """两阶段策略判定：规则 PRECISE 直接返回；否则长问题用 LLM 校正，短问题信规则。"""
    strategy = _fast_rag_strategy(query)
    if strategy == "PRECISE":
        return strategy
    if len(query.strip()) >= 18:
        return await _determine_rag_strategy(query)
    return strategy


async def _model_general_hint(query: str) -> Optional[bool]:
    """factory.classify 软提示：仅在分类器真实加载时采信其 general 判定，避免未配置时的通用兜底误判。"""
    factory = app_state.llm_factory
    if factory is None or factory.get_cached("classifier") is None:
        return None
    try:
        label = await factory.classify(query)
    except Exception as e:  # noqa: BLE001
        logger.exception(f"classify.model_failed | {e}")
        return None
    return label == "general"


# --------------------------------------------------------------------------- #
# 节点①：classify_query — Query 类型判断（含历史摘要加载）
# --------------------------------------------------------------------------- #
async def classify_query_node(state: QAState) -> dict:
    """Query 分类节点，决定走哪条处理路径。

    同时负责从 checkpointer 持久化的 state 读取当前会话的历史摘要
    （参考项目落 qa_sessions 表，本项目用状态承载，不引入新表）。

    返回的 query_type：
      GENERAL  → 跳过 RAG，直接 LLM 回答
      PRECISE  → 直接向量检索
      VAGUE    → 先 HyDE 再检索
      BROAD    → 先 Multi-Query 改写再并行检索
    """
    # 取最后一条 HumanMessage 作为原始输入；兼容统一聊天入口直传的 query
    messages = state.get("messages", [])
    raw_query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            raw_query = str(msg.content)
            break
    if not raw_query:
        raw_query = state.get("query", "")

    # 规则拦截 → 联网指令识别
    original_query, auto_web = _extract_query_and_web_flag(raw_query)

    # 历史摘要从 checkpointer 状态读取（首次进入为 None）
    existing_summary = state.get("existing_summary")

    _base: dict = {
        "original_query": original_query,
        "existing_summary": existing_summary,
        "rewritten_queries": [],
        "hyde_document": None,
        # 自动识别到联网指令，或客户端显式开启，都算开启 Web 兜底
        "enable_web_search": auto_web or bool(state.get("enable_web_search", False)),
    }

    # 规则拦截 → GENERAL（闲聊/时间/打招呼）
    if _rule_classify_general(original_query):
        logger.debug(f"classify.general_by_rule | query={original_query[:50]}")
        return {**_base, "query_type": "GENERAL"}

    # 规则拦截 → 关键词快速通道（知识库相关词）→ RAG 策略快判
    if _rule_classify_specialized(original_query):
        strategy = await _determine_rag_strategy_fast(original_query)
        logger.debug(f"classify.specialized | {strategy=}")
        return {**_base, "query_type": strategy}

    # 模型软提示：分类器已加载且其判定为 general 时直接走通用分支
    hint = await _model_general_hint(original_query)
    if hint is True:
        return {**_base, "query_type": "GENERAL"}

    strategy = await _determine_rag_strategy_fast(original_query)
    logger.debug(f"classify.rag_strategy | {strategy=}")
    return {**_base, "query_type": strategy}


# --------------------------------------------------------------------------- #
# 节点②：hyde_generate — HyDE 假设文档生成（VAGUE 分支）
# --------------------------------------------------------------------------- #
async def hyde_generate_node(state: QAState) -> dict:
    """针对模糊 Query，让 LLM 先生成一段假设性回答文档，用其向量代替原始 Query 向量去检索。"""
    query = state.get("original_query", "")
    messages = state.get("messages", [])
    history = [m for m in _window(messages, 1500) if not isinstance(m, SystemMessage)]

    prompt = ChatPromptTemplate.from_messages(
        [
            MessagesPlaceholder(variable_name="history"),
            ("human", await resolve_prompt("hyde")),
        ]
    )
    llm = await get_llm(QA_AGENT_TYPE)
    chain = prompt | llm | StrOutputParser()
    hyde_content = await chain.ainvoke({"history": history, "query": query})

    logger.debug(f"hyde.done | len={len(hyde_content)}")
    return {"hyde_document": hyde_content}


# --------------------------------------------------------------------------- #
# 节点③：multi_query_rewrite — Multi-Query 改写（BROAD 分支）
# --------------------------------------------------------------------------- #
async def multi_query_rewrite_node(state: QAState) -> dict:
    """针对宽泛/极短 Query，改写为 3-5 个具体子 Query。"""
    query = state.get("original_query", "")
    messages = state.get("messages", [])
    history = [m for m in _window(messages, 1000) if not isinstance(m, SystemMessage)]

    prompt = ChatPromptTemplate.from_messages(
        [
            MessagesPlaceholder(variable_name="history"),
            ("human", await resolve_prompt("multi_query_rewrite")),
        ]
    )
    llm = await get_llm(QA_AGENT_TYPE)
    chain = prompt | llm | StrOutputParser()
    result = await chain.ainvoke({"history": history, "query": query})

    rewritten = [line for line in result.split("\n") if line.strip()]
    if not rewritten:  # 改写失败时回退为原始查询
        rewritten = [query]
    logger.debug(f"multi_query_rewrite.done | count={len(rewritten)} | queries={rewritten}")
    return {"rewritten_queries": rewritten}


# --------------------------------------------------------------------------- #
# 节点④：retrieve — 混合召回 + BGE 精排（backend/rag 自研闭环）
# --------------------------------------------------------------------------- #
async def retrieve_node(state: QAState) -> dict:
    """调用 backend.rag.retrieval 完成检索与精排，直接输出 ranked_chunks。"""
    query_type = state.get("query_type", "PRECISE").upper()
    tenant_id = int(state.get("tenant_id", 0))
    original_query = state.get("original_query", "")

    # BROAD：并行多 Query 检索，合并去重（全文哈希为 key，同一内容保留最高分）
    if query_type == "BROAD" and state.get("rewritten_queries"):
        broad_queries = state["rewritten_queries"]

        async def _one(sub_query: str) -> List[Chunk]:
            return await retrieve_chunks(
                sub_query, tenant_id, top_k=config.qa.broad_per_query_top_k
            )

        results = await asyncio.gather(*[_one(q) for q in broad_queries], return_exceptions=True)
        seen: dict[str, Chunk] = {}
        for res in results:
            if isinstance(res, Exception):
                logger.warning(f"retrieve.subquery_failed | {res}")
                continue
            for doc in res:
                key = _dedup_key(doc.content)
                if key not in seen or doc.score > seen[key].score:
                    seen[key] = doc
        merged = sorted(seen.values(), key=lambda d: d.score, reverse=True)[: config.qa.merge_top_k]
    else:
        # PRECISE / VAGUE：单路检索
        if query_type == "VAGUE" and state.get("hyde_document"):
            query_text = state["hyde_document"]
            top_k = config.qa.vague_top_k
        else:
            query_text = original_query
            top_k = config.qa.precise_top_k
        merged = await retrieve_chunks(query_text or "", tenant_id, top_k=top_k)

    ranked_chunks = [
        RankedChunk(
            content=d.content,
            score=d.score,
            source=d.source,
            doc_id=d.doc_id,
            chunk_id=d.chunk_id,
            metadata=d.metadata,
            parent_id=d.parent_id,
            parent_content=d.parent_content,
            highlighted_content=d.highlighted_content,
            chunk_type=d.chunk_type,
            extra=d.extra,
        )
        for d in merged
    ]
    # confidence 语义：精排分数（0~1，可直接比较阈值）；
    # 精排不可用时 score 是 RRF 融合分（0.0x），只能排序不能当相似度 → 命中即视为可生成。
    rerank_used = True
    if ranked_chunks:
        extra = ranked_chunks[0].extra or {}
        rerank_used = bool(extra.get("_rerank_used", True))
    if ranked_chunks and rerank_used:
        confidence = ranked_chunks[0].score
    elif ranked_chunks:
        confidence = 1.0  # 粗排命中：分数不可比，避免误判低置信
    else:
        confidence = 0.0
    is_high_confidence = confidence >= config.qa.high_confidence_threshold

    logger.debug(
        f"retrieve.done | {query_type=} | ranked={len(ranked_chunks)} "
        f"| {rerank_used=} | {confidence=} | {is_high_confidence=}"
    )
    return {
        "ranked_chunks": ranked_chunks,
        "confidence": confidence,
        "is_high_confidence": is_high_confidence,
    }


# --------------------------------------------------------------------------- #
# 节点⑤：高置信度 RAG 生成
# --------------------------------------------------------------------------- #
async def generate_rag_node(state: QAState) -> dict:
    """高置信度 RAG 生成节点。"""
    ranked_chunks = state.get("ranked_chunks", [])
    query = state.get("original_query", "")
    messages = state.get("messages", [])
    summary = state.get("existing_summary")

    # 父子片 small-to-big：优先用"父片内高亮子片"的完整上下文；
    # 同一父片被多个子片命中时只取一次，避免重复把同一段上下文塞进 prompt。
    context_parts, sources, seen_parents = [], [], set()
    use_highlight = config.qa.parent_context_by_highlight
    for chunk in ranked_chunks:
        key = chunk.parent_id or chunk.chunk_id or str(len(context_parts))
        if key in seen_parents:
            continue
        seen_parents.add(key)
        body = (
            chunk.highlighted_content
            if use_highlight and chunk.highlighted_content
            else (chunk.parent_content if use_highlight and chunk.parent_content else chunk.content)
        )
        context_parts.append(f"【参考{len(context_parts) + 1}】\n{body}")
        src = chunk.source or chunk.metadata.get("source_location", "")
        if src and src not in sources:
            sources.append(src)

    context = "\n\n".join(context_parts)
    history = [m for m in _window(messages, 2500) if not isinstance(m, SystemMessage)]

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", await _build_full_system_prompt(summary)),
            MessagesPlaceholder(variable_name="history"),
            ("human", await resolve_prompt("rag_answer")),
        ]
    )
    llm = await get_llm(QA_AGENT_TYPE, thinking=bool(state.get("thinking")))
    chain = prompt | llm | StrOutputParser()
    answer = await chain.ainvoke({"history": history, "context": context, "query": query})

    sources_text = "\n".join([f"  • {s}" for s in sources])
    final_answer = f"{answer}\n\n**参考来源**\n{sources_text}" if sources else answer

    logger.debug(f"generate_rag.done | answer_length={len(final_answer)}")
    return {
        "answer": final_answer,
        "sources": sources,
        "answer_mode": "rag",
        "fallback_used": False,
        "should_summarize": _should_summarize(messages),
        "messages": [AIMessage(content=final_answer)],
        "structured_output": {
            "answer": final_answer,
            "sources": sources,
            "confidence": state.get("confidence", 0),
            "answer_mode": "rag",
        },
    }


# --------------------------------------------------------------------------- #
# 节点⑥：web_search — Web 搜索补充（低置信度分支）
# --------------------------------------------------------------------------- #
async def web_search_node(state: QAState) -> dict:
    """低置信度分支的 Web 搜索节点。

    知识库置信度不足时，调用 web_search 能力补充互联网信息。能力不可用时静默降级，
    返回空列表，不阻断后续生成节点。
    """
    try:
        registry = app_state.plugin_registry
        if registry is None:
            return {"web_search_results": []}
        results = await registry.call(
            "web_search",
            query=state.get("original_query", ""),
            max_results=config.qa.web_search_max_results,
        )
        results = results or []
        web_search_results = [WebSearchResult(**r) if isinstance(r, dict) else r for r in results]
        logger.debug(f"web_search.done | count={len(web_search_results)}")
        return {"web_search_results": web_search_results}
    except Exception as e:  # noqa: BLE001
        logger.exception(f"web_search.failed | {e}")
        return {"web_search_results": []}


async def _general_answer(state: QAState, current_prompt: str) -> str:
    """通用回答生成：注入历史摘要、Web 搜索结果，调用 LLM 直答。"""
    query = state.get("original_query", "")
    messages = state.get("messages", [])
    summary = state.get("existing_summary")

    web_results = state.get("web_search_results") or []
    web_context = ""
    if web_results:
        web_context = "\n".join(
            f"[{i}] {r.title}（{r.url}）\n{r.snippet[:512]}" for i, r in enumerate(web_results, 1)
        )

    history = [m for m in _window(messages, 1500) if not isinstance(m, SystemMessage)]
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", await _build_full_system_prompt(summary)),
            MessagesPlaceholder(variable_name="history"),
            ("human", current_prompt),
        ]
    )
    llm = await get_llm(QA_AGENT_TYPE, thinking=bool(state.get("thinking")))
    chain = prompt | llm | StrOutputParser()
    return await chain.ainvoke({"history": history, "query": query, "web_context": web_context})


# --------------------------------------------------------------------------- #
# 节点⑦：低置信度 LLM 直答（含 Web 搜索补充）
# --------------------------------------------------------------------------- #
async def generate_direct_node(state: QAState) -> dict:
    """低置信度大模型直接回答。"""
    messages = state.get("messages", [])
    web_results = state.get("web_search_results") or []
    web_sources = [r.url for r in web_results if r.url]
    retrieved_refs = _retrieved_source_refs(state)

    answer = await _general_answer(state, await resolve_prompt("direct_answer"))

    if web_sources:
        final_answer = answer
        answer_mode = "web_augmented"
        sources = web_sources
    else:
        final_answer = (
            f"{answer}\n\n**说明**：以上为 AI 基于通用知识的回答，"
            f"知识库中{'有低相关候选内容但未直接采用' if retrieved_refs else '暂无高相关内容'}。"
        )
        answer_mode = "llm_direct"
        # 无外部来源时也写一条可解释的标记，避免 sources 永远是空数组
        sources = retrieved_refs or [NO_EXTERNAL_SOURCE]

    logger.debug(
        f"generate_direct.done | answer_length={len(final_answer)} | "
        f"web_sources={len(web_sources)} | source_refs={len(sources)}"
    )
    return {
        "answer": final_answer,
        "sources": sources,
        "answer_mode": answer_mode,
        "fallback_used": True,
        "should_summarize": _should_summarize(messages),
        "messages": [AIMessage(content=final_answer)],
        "structured_output": {
            "answer": final_answer,
            "sources": sources,
            "confidence": state.get("confidence", 0),
            "answer_mode": answer_mode,
        },
    }


# --------------------------------------------------------------------------- #
# 节点⑧：通用问题直答（跳过 RAG）
# --------------------------------------------------------------------------- #
async def generate_general_node(state: QAState) -> dict:
    """通用问题直答节点：打招呼、问时间、闲聊等与知识库无关的问题。"""
    messages = state.get("messages", [])
    web_results = state.get("web_search_results") or []
    web_sources = [r.url for r in web_results if r.url]

    answer = await _general_answer(state, await resolve_prompt("general_answer"))

    answer_mode = "web_augmented" if web_sources else "general"
    sources = web_sources or [NO_EXTERNAL_SOURCE]
    logger.debug(
        f"generate_general.done | answer_length={len(answer)} | "
        f"web_sources={len(web_sources)} | source_refs={len(sources)}"
    )
    return {
        "answer": answer,
        "sources": sources,
        "answer_mode": answer_mode,
        "fallback_used": bool(web_sources),
        "should_summarize": _should_summarize(messages),
        "messages": [AIMessage(content=answer)],
        "structured_output": {
            "answer": answer,
            "sources": sources,
            "confidence": 1.0,
            "answer_mode": answer_mode,
        },
    }


# --------------------------------------------------------------------------- #
# 节点⑨：enqueue_pending — 低置信度问题入知识沉淀待审队列
# --------------------------------------------------------------------------- #
async def enqueue_pending_node(state: QAState) -> dict:
    """将低置信度问题写入知识沉淀待审队列（agent_knowledge_pending_queue），供教师复核补库。

    仅当置信度低于阈值（config.qa.high_confidence_threshold）才入队：路由层虽已按
    is_high_confidence 分流，但 confidence 在 retrieve 与入队之间可能被 web 检索节点改过，
    这里用最新值再判一次，避免边界或回升后的问题被无谓入队。失败静默（仅告警）；
    返回 {} 不修改 State。
    """
    try:
        confidence = float(state.get("confidence", 0.0))
        if confidence >= config.qa.high_confidence_threshold:
            logger.debug(f"enqueue_pending.skipped | confidence={confidence} >= threshold")
            return {}
        tenant_id = int(state.get("tenant_id", 0))
        user_id = int(state.get("user_id", 0))
        if tenant_id and user_id:
            from backend.data.dao.business.knowledge_pending_queue_dao import (
                KnowledgePendingQueueDao,
            )

            await KnowledgePendingQueueDao.insert_pending(
                tenant_id=tenant_id,
                user_id=user_id,
                question=str(state.get("original_query", "")),
                confidence=confidence,
            )
            logger.debug(f"enqueue_pending.done | q={state.get('original_query', '')[:50]}")
    except Exception as e:  # noqa: BLE001 - SQL 异常必须暴露，不降级
        logger.exception(f"enqueue_pending.failed | {e}")
        raise
    return {}


# --------------------------------------------------------------------------- #
# 节点⑩：save_memory — 记忆保存（条件触发摘要压缩，写回 checkpointer 状态）
# --------------------------------------------------------------------------- #
async def _compress_summary(messages: List, existing_summary: Optional[str]) -> str:
    """用 LLM 把最近对话压缩成摘要；失败抛出由调用方降级。"""
    history = [m for m in _window(messages, 2500) if not isinstance(m, SystemMessage)]
    if not history:
        return existing_summary or ""
    history_text = "\n".join(
        f"{'用户' if isinstance(m, HumanMessage) else '助手'}: {m.content}" for m in history
    )
    prompt = ChatPromptTemplate.from_messages([("human", await resolve_prompt("summary"))])
    llm = await get_llm(QA_AGENT_TYPE)
    chain = prompt | llm | StrOutputParser()
    return await chain.ainvoke({"summary": existing_summary or "（无）", "history": history_text})


async def save_memory_node(state: QAState) -> dict:
    """记忆保存节点：对话轮数达到阈值时压缩历史并写回 state（由 checkpointer 持久化）。

    参考项目落 qa_sessions 表，本项目直接把摘要写回 QAState，由 AsyncPostgresSaver
    跨轮持久，无需新建表。两步均失败静默，不中断流程。返回 {} 不修改 State。
    """
    messages = state.get("messages", [])
    summary = state.get("existing_summary")

    # 条件触发摘要压缩：优先采用生成节点置位的 should_summarize 标志（数据可观测、阈值可配），
    # 并保留对 messages 轮数的兜底判断以确保安全。
    triggered = state.get("should_summarize", False) or _should_summarize(messages)
    if triggered:
        try:
            summary = await _compress_summary(messages, summary)
            logger.debug("save_memory.summary_compressed")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"save_memory.compress_failed | {e}")

    if summary:
        # 摘要压缩成功 → 抽取长期记忆块并写入 agent_long_term_memory（跨会话复用）
        if triggered:
            from backend.services.memory_hooks import persist_long_term

            await persist_long_term(agent_id="qa", state=state, summary=summary)
            logger.debug("save_memory.long_term_persisted")
        return {"existing_summary": summary}
    return {}
