"""模拟面试工作流节点实现。"""

import asyncio
import json

from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from sqlalchemy import text

from backend.agents.interview.prompts import (
    resolve_prompt,
    resolve_prompt_item,
)
from backend.agents.interview.state import (
    InterviewState,
    InterviewStage,
    AnswerQuality,
    InterviewReport,
)
from backend.common.llm.llm_factory import get_llm, get_structured_llm
from backend.common.logger import get_logger
from backend.data.sql import session_scope

logger = get_logger("interview_nodes")

DEFAULT_MAX_TURNS = 40  # 一场面试的总轮数上限（兜底防止无限进行）
MAX_FOLLOWUP_PER_QUESTION = 2  # 同一道题最多追问几次
SUMMARY_TRIGGER_MESSAGES = 30  # 消息超过该数量时触发摘要压缩

# 各阶段「最少 / 最多」轮数
STAGE_MIN_TURNS = {
    InterviewStage.WARMUP.value: 1,  # 热身至少 1 轮（自我介绍完即可推进）
    InterviewStage.TECH_BASE.value: 6,  # 技术环节至少 6 轮
    InterviewStage.PROJECT.value: 2,  # 项目环节至少 2 轮
    InterviewStage.CLOSING.value: 2,  # 反问环节至少 2 轮
}

STAGE_MAX_TURNS = {
    InterviewStage.WARMUP.value: 4,  # 热身最多 4 轮（避免卡住）
    InterviewStage.TECH_BASE.value: 12,  # 技术环节最多 12 轮
    InterviewStage.PROJECT.value: 14,  # 项目环节最多 14 轮
    InterviewStage.CLOSING.value: 4,  # 反问环节最多 4 轮
}


def _msg_text(msg: BaseMessage) -> str:
    """安全提取消息文本，兼容 str 和 list（多模态）content"""
    content = msg.content
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content)


def _trim_messages_to_window(messages: list[BaseMessage], window: int = 10) -> list[BaseMessage]:
    """保留最近 window 条消息，且不把 SystemMessage 带进历史。"""
    if window <= 0:
        return []
    return [m for m in messages[-window:] if not isinstance(m, SystemMessage)]


def _should_trigger_summary(messages: list[BaseMessage]) -> bool:
    """消息过多时触发一次摘要压缩，避免 checkpointer 状态无限增长。"""
    return len(messages) >= SUMMARY_TRIGGER_MESSAGES


async def _compress_to_summary(messages: list[BaseMessage], existing_summary: str | None) -> str:
    """把早期对话压缩成摘要；失败时保留旧摘要。"""
    conversation = "\n".join(
        f"{'面试官' if isinstance(m, AIMessage) else '学员'}：{_msg_text(m)}"
        for m in messages[-40:]
        if isinstance(m, (HumanMessage, AIMessage))
    )
    prompt = (await resolve_prompt("summary")).format(
        existing_summary=existing_summary or "（无）",
        conversation=conversation[:6000],
    )
    llm = await get_llm("interview")
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    return _msg_text(response).strip() or (existing_summary or "")


async def _stream_text(llm: object, messages: list[BaseMessage]) -> str:
    """流式调用 LLM 并聚合完整文本，让 SSE 能拿到 token 事件。"""
    parts: list[str] = []
    async for chunk in llm.astream(messages):  # type: ignore[attr-defined]
        text = _msg_text(chunk)
        if text:
            parts.append(text)
    return "".join(parts)


async def _generate_questions_by_llm(target_position: str, count: int = 8) -> list:
    """
    根据目标岗位用 大模型动态生成技术面试题，作为 DB 题库的替代/补充

    参数：target_position（岗位，决定出题方向）、count（题数，默认 8）
    返回：题目字典列表，每项 = {id, content, difficulty, tags, asked}；失败返回 []
    """
    try:
        llm = await get_llm("interview")
        prompt = (await resolve_prompt("tech_base_generate")).format(
            position=target_position,
            count=count,
        )
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        thy_text = _msg_text(response).strip()

        # 兼容大模型有时用 ```json ... ``` 包裹输出：把里面以 [ 开头的那段抠出来
        if "```" in thy_text:
            parts = thy_text.split("```")
            for part in parts:
                stripped = part.strip()
                if stripped.startswith("json"):
                    stripped = stripped[4:].strip()
                if stripped.startswith("["):
                    thy_text = stripped
                    break

        questions_raw = json.loads(thy_text)
        result = []
        for i, q in enumerate(questions_raw):
            if not isinstance(q, dict) or not q.get("content"):
                continue
            result.append(
                {
                    "id": f"llm_{i}",
                    "content": q["content"],
                    "difficulty": q.get("difficulty", "medium"),
                    "tags": q.get("tags", [target_position]),
                    "asked": False,
                }
            )
        logger.info(
            f"generate_questions_llm.done | count={len(result)} | position={target_position}"
        )
        return result
    except Exception as e:
        logger.exception(f"generate_questions_llm.failed | {e}")
        return []


async def load_context_node(state: InterviewState) -> dict:
    """加载面试上下文：简历联动、题库、历史摘要。

    首轮初始化阶段/计数；后续只刷新摘要。所有查询都按 tenant_id + user_id
    过滤，避免跨租户读取简历或题库。
    """
    user_id = state.get("user_id")
    tenant_id = state.get("tenant_id")
    thread_id = state.get("thread_id")
    session_id = state.get("session_id")
    if not user_id or not tenant_id or not thread_id or not session_id:
        logger.error(f"load_context.missing_ids | keys={list(state.keys())}")
        return {}

    is_first_turn = state.get("total_turn_count", 0) == 0
    updates: dict = {}

    async def _fetch_resume(review_id: str) -> dict:
        try:
            async with session_scope() as session:
                row = (
                    (
                        await session.execute(
                            text(
                                "SELECT structured_data FROM agent_resume_reviews "
                                "WHERE id = CAST(:id AS uuid) AND tenant_id = :tenant_id"
                            ),
                            {"id": review_id, "tenant_id": tenant_id},
                        )
                    )
                    .mappings()
                    .first()
                )
            raw = row["structured_data"] if row else None
            if not raw:
                return {}
            structured = raw if isinstance(raw, dict) else json.loads(raw)
            return {
                "resume_projects": structured.get("projects", []),
                "resume_skills": structured.get("skills_list") or structured.get("skills", []),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"load_context.resume_load_failed | {exc}")
            return {}

    async def _fetch_questions(target: str) -> list[dict]:
        try:
            async with session_scope() as session:
                rows = (
                    (
                        await session.execute(
                            text(
                                """
                            SELECT id, content, difficulty, tags
                            FROM agent_interview_questions
                            WHERE tenant_id = :tenant_id
                              AND (target_position = :target OR target_position = 'general')
                              AND is_active = TRUE
                            ORDER BY
                                CASE difficulty
                                    WHEN 'medium' THEN 1
                                    WHEN 'easy' THEN 2
                                    ELSE 3
                                END,
                                RANDOM()
                            LIMIT 20
                            """
                            ),
                            {"tenant_id": tenant_id, "target": target},
                        )
                    )
                    .mappings()
                    .all()
                )
            return [
                {
                    "id": str(r["id"]),
                    "content": r["content"],
                    "difficulty": r["difficulty"],
                    "tags": r["tags"] if isinstance(r["tags"], list) else [],
                    "asked": False,
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"load_context.question_bank_failed | {exc}")
            return []

    async def _fetch_summary() -> str | None:
        # 摘要改为只存 U checkpoint（existing_summary），由统一层维护（§5.4）；
        # 统一层未接入前从 state 注入的 existing_summary 读取，不再查业务表 summary 列。
        return state.get("existing_summary")

    if is_first_turn:
        updates.update(
            {
                "current_stage": InterviewStage.WARMUP.value,
                "stage_turn_count": 0,
                "total_turn_count": 0,
                "followup_count": 0,
                "projects_asked": [],
                "last_answer_quality": AnswerQuality.ADEQUATE.value,
                "max_turns": DEFAULT_MAX_TURNS,
                "report": None,
                "should_summarize": False,
                "resume_projects": state.get("resume_projects") or [],
                "resume_skills": state.get("resume_skills") or [],
            }
        )
        resume_review_id = state.get("resume_review_id")
        target = state.get("target_position", "")

        async def _noop_resume() -> dict:
            return {}

        resume_coro = _fetch_resume(resume_review_id) if resume_review_id else _noop_resume()
        resume_data, db_questions, llm_questions, existing_summary = await asyncio.gather(
            resume_coro,
            _fetch_questions(target),
            _generate_questions_by_llm(target),
            _fetch_summary(),
        )

        question_bank = (llm_questions or []) + (db_questions or [])
        if resume_data:
            updates["resume_projects"] = resume_data.get("resume_projects", [])
            updates["resume_skills"] = resume_data.get("resume_skills", [])
            logger.info(f"load_context.resume_loaded | projects={len(updates['resume_projects'])}")

        updates["question_bank"] = question_bank
        updates["existing_summary"] = existing_summary
        logger.info(f"load_context.question_bank_loaded | count={len(question_bank)}")
    else:
        updates["existing_summary"] = await _fetch_summary()

    return updates


async def check_stage_node(state: InterviewState) -> dict:
    """
    阶段推进节点（纯逻辑，不调 LLM）：判断当前阶段是否要推进 / 强制结束

    读取 state：
        current_stage / stage_turn_count / total_turn_count / max_turns / messages
        （TECH_BASE 还看 question_bank，PROJECT 还看 resume_projects/projects_asked）
    返回（写回 state）：
        推进时：{current_stage: 新阶段, stage_turn_count:0, followup_count:0, current_question:None}
        不推进：{}（空 dict，什么都不改）

    阶段推进条件：
        WARMUP → TECH_BASE: turns >= 1（学员完成自我介绍）
        TECH_BASE → PROJECT: stage_turns >= 6 或题库问完
        PROJECT → CLOSING:   stage_turns >= 2 或项目全覆盖
        任意 → FINISHED(强制): total_turns >= max-2 或发送结束关键词
        CLOSING → FINISHED:  stage_turns >= 2
    """
    current_stage = state.get("current_stage", InterviewStage.WARMUP.value)  # 当前阶段
    stage_turns = state.get("stage_turn_count", 0)  # 当前阶段已进行轮数
    total_turns = state.get("total_turn_count", 0)  # 总轮数
    max_turns = state.get("max_turns", DEFAULT_MAX_TURNS)  # 轮数上限
    messages = state.get("messages", [])  # 对话消息列表

    # 已结束则不再处理（直接交给后面的条件路由去生成报告）
    if current_stage == InterviewStage.FINISHED.value:
        return {}

    # 从后往前找学员最后一条消息（用于检测"结束面试"关键词）
    latest_student_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):  # 找到第一条 Human 消息
            latest_student_msg = _msg_text(msg)
            break

    # 强制结束判断：总轮数快到上限，或学员主动说要结束 → 直接跳 FINISHED（跳过 CLOSING）
    force_end_keywords = ["结束面试", "不想继续", "面试结束", "结束吧", "到此为止"]
    is_forced_end = (
        total_turns >= max_turns - 2  # 轮数 ≥ 上限-2
        or any(kw in latest_student_msg for kw in force_end_keywords)  # 或命中关键词
    )

    if is_forced_end:  # 触发强制结束
        logger.info("check_stage.forced_to_finished | reason=keyword_or_max_turns")
        return {"current_stage": InterviewStage.FINISHED.value}

    # CLOSING → FINISHED（反问环节满 2 轮就结束）
    if current_stage == InterviewStage.CLOSING.value:
        if stage_turns >= STAGE_MIN_TURNS[InterviewStage.CLOSING.value]:
            logger.info("check_stage.advance | from_stage=closing | to_stage=finished")
            return {"current_stage": InterviewStage.FINISHED.value}
        return {}

    # 常规阶段推进：取当前阶段的最小/最大轮数
    stage_min = STAGE_MIN_TURNS.get(current_stage, 2)  # 至少问几轮才允许推进
    stage_max = STAGE_MAX_TURNS.get(current_stage, 10)  # 问满几轮就强制推进

    should_advance = False
    if stage_turns >= stage_max:
        should_advance = True
    elif stage_turns >= stage_min:
        should_advance = _check_advance_condition(current_stage, state)

    if should_advance:
        next_stage = _next_stage(current_stage)
        logger.info(f"check_stage.advance | from_stage={current_stage} | to_stage={next_stage}")
        return {
            "current_stage": next_stage,
            "stage_turn_count": 0,
            "followup_count": 0,
            "current_question": None,
        }

    return {}


def _check_advance_condition(stage: str, state: InterviewState) -> bool:
    """判断当前阶段「内容上」是否满足推进条件（轮数已达下限后才调用）"""
    if stage == InterviewStage.WARMUP.value:
        return True

    if stage == InterviewStage.TECH_BASE.value:
        bank = state.get("question_bank", [])
        asked_count = sum(1 for q in bank if q.get("asked", False))
        return asked_count >= min(8, len(bank))

    if stage == InterviewStage.PROJECT.value:
        projects = state.get("resume_projects", [])
        projects_asked = state.get("projects_asked", [])
        if not projects:
            return True
        return len(projects_asked) >= len(projects)

    return False


def _next_stage(current: str) -> str:
    """返回下一个阶段的枚举值字符串（按固定顺序往后走一格）"""
    order = [
        InterviewStage.WARMUP.value,
        InterviewStage.TECH_BASE.value,
        InterviewStage.PROJECT.value,
        InterviewStage.CLOSING.value,
        InterviewStage.FINISHED.value,
    ]
    try:
        idx = order.index(current)
        return (
            order[idx + 1] if idx + 1 < len(order) else InterviewStage.FINISHED.value
        )  # 下一个；到尾就 FINISHED
    except ValueError:
        return InterviewStage.CLOSING.value


def _get_last_student_answer(messages: list) -> str:
    """提取消息列表中最后一条学员（Human）消息的文本"""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return _msg_text(msg)
    return ""


async def evaluate_answer_node(state: InterviewState) -> dict:
    """
    评估学员上一轮回答质量（EXCELLENT / ADEQUATE / WEAK / NO_ANSWER）

    读取 state：
        total_turn_count / current_stage  判断是否跳过评估
        messages                          取学员最后一条回答
        current_question                  取当前题干（评估时作上下文）
        stage_turn_count                  用于 +1
    返回（写回 state）：
        last_answer_quality  本轮质量标签（给 generate_response 决定追问/换题）
        total_turn_count / stage_turn_count  各 +1（轮次真实发生）

    首轮和热身阶段不评估，直接返回 ADEQUATE
    """
    total_turns = state.get("total_turn_count", 0)  # 当前总轮数
    current_stage = state.get("current_stage", InterviewStage.WARMUP.value)  # 当前阶段
    messages = state.get("messages", [])  # 对话消息

    # 首轮或热身阶段跳过评估：直接给中性标签 ADEQUATE，但计数照常 +1
    if total_turns == 0 or current_stage == InterviewStage.WARMUP.value:
        return {
            "last_answer_quality": AnswerQuality.ADEQUATE.value,  # 默认质量
            "total_turn_count": total_turns + 1,  # 总轮数 +1
            "stage_turn_count": state.get("stage_turn_count", 0) + 1,  # 阶段轮数 +1
        }
    student_answer = _get_last_student_answer(messages)  # 取学员最后一条回答文本

    # 明确未作答：空回答，或直说"不知道/不清楚/没学过" → 直接 NO_ANSWER，省一次 LLM
    if not student_answer.strip() or student_answer.strip() in ["不知道", "不清楚", "没学过"]:
        return {
            "last_answer_quality": AnswerQuality.NO_ANSWER.value,  # 标记未作答
            "total_turn_count": total_turns + 1,  # 计数照常 +1
            "stage_turn_count": state.get("stage_turn_count", 0) + 1,
        }

    current_q = state.get("current_question") or {}  # 当前题（可能为空 dict）
    question_text = current_q.get("content", "上一个问题")  # 题干（缺省占位）
    answer_text = student_answer[:800]  # 回答截断到 800 字，控制 token

    # ── 第一步：Think Tool 推理分析（不约束格式，让 大模型写判断依据）──
    reasoning_trace = ""
    try:
        think_prompt = (await resolve_prompt("evaluate_think")).format(
            question=question_text,
            answer=answer_text,
        )
        think_llm = await get_llm("interview")
        think_resp = await think_llm.ainvoke([HumanMessage(content=think_prompt)])
        reasoning_trace = _msg_text(think_resp).strip()
        logger.debug(f"evaluate_think.done | stage={current_stage}")
    except Exception as e:
        logger.exception(f"evaluate_think.failed | {e}")

    # ── 第二步：主评估，把第一步的推理结论注入 prompt 末尾 ───────
    think_context = (
        f"\n\n【评估前分析】\n{reasoning_trace}" if reasoning_trace else ""  # 有推理才追加
    )
    prompt = (await resolve_prompt("evaluate_answer")).format(  # 拼主评估 Prompt
        question=question_text,
        answer=answer_text,
    ) + think_context

    try:
        llm = await get_llm("interview")
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        quality_str = _msg_text(response).strip().lower()

        # 用 in 匹配（大模型可能带空格/换行），命中哪个就用哪个标签
        if "excellent" in quality_str or "优秀" in quality_str:
            quality = AnswerQuality.EXCELLENT.value
        elif "weak" in quality_str or "较弱" in quality_str:
            quality = AnswerQuality.WEAK.value
        elif "no_answer" in quality_str or "未作答" in quality_str:
            quality = AnswerQuality.NO_ANSWER.value
        else:
            quality = AnswerQuality.ADEQUATE.value
    except Exception as e:
        logger.exception(f"evaluate_answer.failed | {e}")
        quality = AnswerQuality.ADEQUATE.value

    logger.info(
        f"evaluate_answer.done | stage={current_stage} | quality={quality} | "
        f"total_turns={total_turns + 1}"
    )

    return {
        "last_answer_quality": quality,  # 本轮质量标签
        "total_turn_count": total_turns + 1,  # 总轮数 +1
        "stage_turn_count": state.get("stage_turn_count", 0) + 1,  # 阶段轮数 +1
    }


async def generate_response_node(state: InterviewState) -> dict:
    """
    分派主函数：根据当前阶段调用对应子函数生成面试官回应

    读取 state：
        current_stage    决定分派到哪个 _respond_*
        stage_turn_count 判断是否刚切换阶段（==1 → 插过渡语）
        messages         传给子函数 + 判断是否触发摘要
    返回（写回 state）：
        messages          面试官这一轮的回复（AIMessage）
        should_summarize  本轮是否要触发摘要压缩
        以及各 _respond_* 子函数返回的字段（如 current_question / projects_asked / followup_count）

    PROJECT/CLOSING 阶段刚切换时（stage_turns==1）插入静态过渡语；
    TECH_BASE 的过渡（介绍评价+第一题）由 _respond_tech_base 内部处理
    """
    current_stage = state.get("current_stage", InterviewStage.WARMUP.value)  # 当前阶段
    stage_turns = state.get("stage_turn_count", 0)  # 当前阶段轮数
    messages = state.get("messages", [])  # 对话消息

    # 阶段刚切换时（stage_turns==1）插入静态过渡语；只 PROJECT 和 CLOSING 用
    transition_prefix = ""
    if stage_turns == 1 and current_stage not in (
        InterviewStage.WARMUP.value,
        InterviewStage.TECH_BASE.value,
    ):
        transition_prefix = await resolve_prompt_item("stage_transitions", current_stage, "")

    # 按阶段分派到对应子函数，各自返回 (回复文本, 要写回的 updates)
    if current_stage == InterviewStage.WARMUP.value:
        response_text, updates = await _respond_warmup(state)
    elif current_stage == InterviewStage.TECH_BASE.value:
        response_text, updates = await _respond_tech_base(state)
    elif current_stage == InterviewStage.PROJECT.value:
        response_text, updates = await _respond_project(state)
    elif current_stage == InterviewStage.CLOSING.value:
        response_text, updates = await _respond_closing(state)
    else:  # FINISHED 等：兜底文案
        response_text = "感谢您参加本次模拟面试，请稍等，正在生成评估报告..."
        updates = {}

    if transition_prefix:  # 有过渡语就拼到回复开头
        response_text = transition_prefix + "\n\n" + response_text

    updates["messages"] = [AIMessage(content=response_text)]  # 面试官回复（追加进 messages）
    updates["should_summarize"] = _should_trigger_summary(messages)  # 判断是否该压缩摘要

    logger.info(
        f"generate_response.done | stage={current_stage} | response_length={len(response_text)}"
    )

    return updates  # 返回更新，写回 state


async def _build_system_with_summary(state: InterviewState) -> str:
    """构建包含历史摘要的 System Prompt（有摘要就追加，让面试官"记得"早前对话）"""
    position = state.get("target_position", "软件工程师")  # 岗位
    system = (await resolve_prompt("system")).format(position=position)  # Nacos 优先
    summary = state.get("existing_summary")  # 历史摘要（可能为空）
    if summary:  # 有摘要才追加
        system += f"\n\n【学员面试历史摘要】\n{summary}"
    return system


def _build_messages(
    system: str,  # System Prompt 文本
    history: list,  # 完整对话历史
    current_prompt: str,  # 本轮要让 大模型做的"任务描述"
    window: int = 10,  # 滑动窗口大小（保留最近几条历史）
) -> list:
    """
    构建发送给 大模型的消息列表：
        [SystemMessage] + 滑动窗口历史（排除最后一条学员消息）+ current_prompt
    """
    result: list[BaseMessage] = [SystemMessage(content=system)]  # 第一条永远是 System
    # history[:-1] 排除最后一条学员消息（它已在 evaluate_answer 处理过，且 current_prompt 已涵盖）
    windowed = _trim_messages_to_window(history[:-1], window)  # 截取最近 window 条
    for msg in windowed:
        if not isinstance(msg, SystemMessage):  # 跳过历史里的 System（避免重复）
            result.append(msg)
    result.append(HumanMessage(content=current_prompt))  # 末尾追加本轮任务描述
    return result


async def _respond_warmup(state: InterviewState) -> tuple[str, dict]:
    """破冰热身阶段：只生成欢迎开场白，邀请自我介绍（WARMUP 仅 1 轮）"""
    messages = state.get("messages", [])
    position = state.get("target_position", "软件工程师")
    system = await _build_system_with_summary(state)

    prompt = (await resolve_prompt_item("warmup", "opening")).format(position=position)
    llm = await get_llm("interview")
    text = await _stream_text(llm, _build_messages(system, messages, prompt, window=4))
    return text.strip(), {}


async def _respond_tech_base(state: InterviewState) -> tuple[str, dict]:
    """
    技术基础阶段：出题或追问

    读取 state：
        last_answer_quality  上轮质量（EXCELLENT 才追问）
        followup_count       当前题已追问次数（上限 2）
        current_question     当前题（None 表示要出新题）
        question_bank        题库（按 asked 标记选下一题）
        stage_turn_count     ==1 表示刚从 WARMUP 切来
        target_position      岗位
    返回 (回复文本, updates)，updates 可能含：
        question_bank（标记 asked）/ current_question / followup_count
    """
    messages = state.get("messages", [])  # 对话历史
    quality = state.get("last_answer_quality", AnswerQuality.ADEQUATE.value)  # 上轮质量
    followup_count = state.get("followup_count", 0)  # 当前题已追问次数
    current_q = state.get("current_question")  # 当前题
    bank = state.get("question_bank", [])  # 题库
    stage_turns = state.get("stage_turn_count", 0)  # 本阶段轮数
    position = state.get("target_position", "软件工程师")  # 岗位
    system = await _build_system_with_summary(state)  # 带摘要的 System Prompt
    updates: dict = {}  # 收集要写回的字段

    # ── 路径1·特殊：刚从 WARMUP 推进而来（stage_turns==1，尚无 current_question）──
    if stage_turns == 1 and current_q is None:
        unasked = [q for q in bank if not q.get("asked", False)]  # 未问过的题
        if not unasked:  # 题库空：给一句兜底
            return "感谢你的自我介绍！接下来我们开始技术基础环节", {}

        first_q = unasked[0]  # 取第一道题
        new_bank = [{**q, "asked": True} if q["id"] == first_q["id"] else q for q in bank]
        updates["question_bank"] = new_bank
        updates["current_question"] = first_q
        updates["followup_count"] = 0

        intro_text = _get_last_student_answer(messages)
        prompt = (await resolve_prompt("intro_eval_tech_first")).format(
            intro=intro_text[:500],
            position=position,
            first_question=first_q["content"],
        )
        llm = await get_llm("interview")
        text = await _stream_text(llm, _build_messages(system, messages, prompt, window=4))
        return text.strip(), updates

    # 判断是否追问当前题：只有回答 EXCELLENT 且没追问满 2 次才追问
    should_followup = (
        current_q is not None
        and followup_count < MAX_FOLLOWUP_PER_QUESTION
        and quality == AnswerQuality.EXCELLENT.value
    )

    if should_followup:
        tech_stack_str = ", ".join((current_q or {}).get("tags", []))
        prompt = (await resolve_prompt_item("tech_base", "followup")).format(
            question=(current_q or {}).get("content"),
            answer=_get_last_student_answer(messages)[:600],
            quality=quality,
            tech_stack=tech_stack_str,
        )
        updates["followup_count"] = followup_count + 1
    else:
        unasked = [q for q in bank if not q.get("asked", False)]
        if not unasked:
            return (
                "好的，基础技术问题我们就聊到这里，接下来我想了解一下你的项目经历",
                {"current_question": None},  # 清空当前题
            )

        next_q = unasked[0]
        new_bank = [{**q, "asked": True} if q["id"] == next_q["id"] else q for q in bank]
        updates["question_bank"] = new_bank
        updates["current_question"] = next_q
        updates["followup_count"] = 0

        prev_question = current_q["content"] if current_q else ""
        prev_answer = _get_last_student_answer(messages)[:600]
        prompt = (await resolve_prompt_item("tech_base", "ask_with_feedback")).format(
            question=prev_question,
            answer=prev_answer,
            quality=quality,
            next_question=next_q["content"],
        )

    llm = await get_llm("interview")
    text = await _stream_text(llm, _build_messages(system, messages, prompt, window=8))
    return text.strip(), updates


async def _respond_project(state: InterviewState) -> tuple[str, dict]:
    """
    项目深挖阶段：基于简历项目针对性追问

    读取 state：
        last_answer_quality  上轮质量（EXCELLENT 或 ADEQUATE 都可追问，门槛比技术环节低）
        followup_count       当前项目已追问次数（上限 2）
        resume_projects      简历项目列表
        projects_asked       已深挖过的项目名
        current_question     当前正在深挖的项目（动态构造的 dict）
        target_position      岗位
    返回 (回复文本, updates)，updates 可能含：
        followup_count / current_question / projects_asked
    """
    messages = state.get("messages", [])  # 对话历史
    quality = state.get("last_answer_quality", AnswerQuality.ADEQUATE.value)  # 上轮质量
    followup_count = state.get("followup_count", 0)  # 当前项目已追问次数
    projects = state.get("resume_projects", [])  # 简历项目
    projects_asked = state.get("projects_asked", [])  # 已深挖的项目名
    current_q = state.get("current_question")  # 当前项目（dict）
    position = state.get("target_position", "工程师")  # 岗位
    system = await _build_system_with_summary(state)  # 带摘要的 System Prompt
    updates: dict = {}  # 收集要写回的字段

    if projects:  # 有简历联动
        # 找下一个还没深挖过的项目
        next_project = None
        for p in projects:
            if p.get("name") not in projects_asked:
                next_project = p
                break

        # 项目环节追问门槛更低：EXCELLENT 或 ADEQUATE 均可追问
        should_followup = (
            current_q is not None
            and followup_count < MAX_FOLLOWUP_PER_QUESTION
            and quality in (AnswerQuality.EXCELLENT.value, AnswerQuality.ADEQUATE.value)
        )

        if should_followup:  # 路径1·追问当前项目
            tech_stack_str = ", ".join((current_q or {}).get("tech_stack", []))
            prompt = (await resolve_prompt_item("project", "followup_with_feedback")).format(
                project_name=(current_q or {}).get("project_name", ""),
                question=(current_q or {}).get("content", ""),
                answer=_get_last_student_answer(messages)[:600],
                quality=quality,
                tech_stack=tech_stack_str,
                question_num=followup_count + 1,
            )
            updates["followup_count"] = followup_count + 1  # 追问次数 +1

        elif next_project:  # 路径2·切到新项目，问第1问
            tech_stack_str = ", ".join(next_project.get("tech_stack", []))
            highlights_str = (
                "\n".join(f"- {h}" for h in next_project.get("highlights", [])) or "（无量化数据）"
            )

            prompt = (await resolve_prompt_item("project", "new_project")).format(
                project_name=next_project["name"],
                project_role=next_project.get("role", "开发者"),
                tech_stack=tech_stack_str,
                highlights=highlights_str,
                description=next_project.get("description", "")[:200],
            )
            updates["current_question"] = {  # 动态构造当前项目 dict（非题库题）
                "content": f"项目深挖：{next_project['name']}",
                "project_name": next_project["name"],
                "tech_stack": next_project.get("tech_stack", []),
            }
            updates["projects_asked"] = projects_asked + [next_project["name"]]  # 记入已深挖
            updates["followup_count"] = 0  # 新项目追问计数清零

        else:  # 路径3·所有项目都深挖完 → 综合题
            prompt = (await resolve_prompt_item("project", "synthesis")).format(position=position)

    else:  # 路径4·无简历联动
        # 基于学员自述出项目题（或架构设计题）
        prompt = (await resolve_prompt_item("project", "no_resume")).format(
            position=position,
            answer=_get_last_student_answer(messages)[:400],
        )

    llm = await get_llm("interview")
    text = await _stream_text(llm, _build_messages(system, messages, prompt, window=10))
    return text.strip(), updates


async def _respond_closing(state: InterviewState) -> tuple[str, dict]:
    """
    反问收尾阶段：开放学员提问

    读取 state：
        stage_turn_count  ≤1 发提问邀请，>1 回应学员的具体问题
        messages          取学员的提问
        target_position   回应时带上岗位上下文
    返回 (回复文本, {})——本阶段不更新状态字段
    """
    messages = state.get("messages", [])  # 对话历史
    stage_turns = state.get("stage_turn_count", 0)  # 本阶段轮数
    position = state.get("target_position", "工程师")  # 岗位
    system = await _build_system_with_summary(state)  # 带摘要的 System Prompt

    if stage_turns <= 1:  # 刚进 CLOSING：邀请学员提问
        prompt = await resolve_prompt_item("closing", "opening")
    else:  # 学员已提问：回应其问题
        last_answer = _get_last_student_answer(messages)  # 学员的提问
        prompt = (await resolve_prompt_item("closing", "respond_question")).format(
            question=last_answer[:300],
            position=position,
        )

    llm = await get_llm("interview")
    text = await _stream_text(llm, _build_messages(system, messages, prompt, window=4))
    return text.strip(), {}


async def generate_report_node(state: InterviewState) -> dict:
    """
    基于完整对话记录和历史摘要，生成五维度结构化评估报告

    读取 state：
        messages           完整对话（取最近 40 条格式化）
        existing_summary   历史摘要（早期对话压缩，作全局视角）
        target_position    岗位
        total_turn_count   总轮数（写进 Prompt 和 structured_output）
        session_id         写进 structured_output
    返回（写回 state）：
        report             五维度报告 dict（给 save_report 存库）
        messages           面试结束通知（AIMessage）
        structured_output  给 API 层直接读的摘要数据
    """
    messages = state.get("messages", [])  # 完整对话
    summary = state.get("existing_summary", "")  # 历史摘要
    position = state.get("target_position", "软件工程师")  # 岗位

    # 取最近 40 条对话，只保留学员/面试官消息，格式化成文本
    recent_messages = [
        msg
        for msg in messages[-40:]  # 最近 40 条
        if isinstance(msg, (HumanMessage, AIMessage))  # 只要人/AI 消息
    ]
    conversation_text = "\n".join(
        [  # 拼成"角色：内容"多行文本
            f"{'面试官' if isinstance(m, AIMessage) else '学员'}：{_msg_text(m)}"
            for m in recent_messages
        ]
    )

    prompt = (await resolve_prompt("generate_report")).format(  # 拼报告 Prompt（双层输入）
        position=position,
        history_summary=summary or "（无历史摘要）",  # 早期对话用摘要
        conversation=conversation_text[:4000],  # 近期对话截断到 4000 字
        total_turns=state.get("total_turn_count", 0),
    )

    structured_llm = await get_structured_llm("interview", InterviewReport)

    report_dict = None
    for attempt in range(2):  # function_calling 偶发返回 None → 判空+重试
        try:
            result: InterviewReport = await structured_llm.ainvoke(
                [
                    SystemMessage(
                        content=(await resolve_prompt("system")).format(position=position)
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            if result is None:
                raise ValueError("structured output returned None")
            report_dict = result.model_dump()
            break
        except Exception as e:
            if attempt == 0:
                logger.exception(f"generate_report.retry | {e}")
                await asyncio.sleep(1)
            else:
                logger.exception(f"generate_report.failed | {e}")

    if report_dict is None:  # 两次均失败 → 硬编码保守报告
        report_dict = {
            "dimensions": [],
            "overall_score": 60,  # 保守默认分，提示报告生成有误
            "strengths": ["参与了完整的模拟面试流程"],
            "improvements": ["建议深化技术基础知识", "加强项目经历的量化描述"],
            "overall_comment": "感谢参加本次模拟面试，请参考各维度建议持续提升",
            "recommended_topics": [],
            "next_step_advice": "建议针对薄弱点系统复习，1-2周后再次模拟面试",
        }

    overall_score = report_dict.get("overall_score", 0)  # 取综合分
    closing_message = (  # 拼面试结束通知（展示给前端）
        f"好的，本次模拟面试到这里就结束了，感谢你的参与！\n\n"
        f"下面是你的整体表现总结：\n\n"
        f"**综合评分：{overall_score} / 100**\n\n"
        f"详细的各维度分析和改进建议可以在面试记录中查看"
    )

    logger.info(
        "generate_report.done",
        overall_score=overall_score,
        dimensions=len(report_dict.get("dimensions", [])),
    )

    return {
        "report": report_dict,  # 给 save_report 存库
        "messages": [AIMessage(content=closing_message)],  # 结束通知（追加进 messages）
        "structured_output": {  # 给 API 层直接读的摘要
            "session_id": state["session_id"],
            "report": report_dict,
            "total_turns": state.get("total_turn_count", 0),
        },
    }


async def save_report_node(state: InterviewState) -> dict:
    """把报告写回 agent_interview_sessions，并标记 finished。

    按业务主键 id（= 会话标识）定位；tenant_id + user_id 避免误写他人会话。
    """
    session_id = state["session_id"]
    tenant_id = state["tenant_id"]
    user_id = state["user_id"]
    report = state.get("report") or {}

    async with session_scope() as session:
        result = await session.execute(
            text(
                """
                UPDATE agent_interview_sessions
                   SET report = CAST(:report AS json),
                       overall_score = :overall_score,
                       status = 'finished',
                       finished_at = now(),
                       updated_at = now()
                 WHERE id = CAST(:session_id AS uuid)
                   AND tenant_id = :tenant_id
                   AND user_id = :user_id
                   AND status <> 'deleted'
                """
            ),
            {
                "report": json.dumps(report, ensure_ascii=False),
                "overall_score": int(report.get("overall_score", 0) or 0),
                "session_id": session_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
            },
        )
        if (result.rowcount or 0) == 0:
            logger.warning(f"save_report.not_found | session_id={session_id}")
        else:
            logger.info(f"save_report.done | session_id={session_id}")

    return {}


async def save_memory_node(state: InterviewState) -> dict:
    """按需压缩历史对话，摘要写入 state（U checkpoint 持久化）。

    业务表无 summary 列（§5.4）；统一层接入前由本节点将 existing_summary 维护进
    checkpoint，避免查/写已删除的 agent_interview_sessions.summary。
    """
    messages = state.get("messages", [])
    summary = state.get("existing_summary")

    if state.get("should_summarize", False):
        try:
            summary = await _compress_to_summary(messages, summary)
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"save_memory.compress_failed | {exc}")

    if not summary:
        return {}
    return {"existing_summary": summary}
