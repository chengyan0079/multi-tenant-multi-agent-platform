"""试卷批阅工作流节点：解析→三轨并行批改→汇总→薄弱点→HITL 复核→发布。"""

import asyncio
import json
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt
from sqlalchemy import text

from backend.agents.exam.prompts import resolve_prompt
from backend.agents.exam.state import (
    ExamState,
    ParsedQuestion,
    ScoringPointItem,
    ByQuestionItem,
    PreReviewSummary,
    SubjectiveReviewResult,
    WeakPointsReport,
    WeakPoint,
    TeacherDecision,
    Modification,
)
from pydantic import TypeAdapter

from backend.common.llm.llm_factory import get_llm, get_structured_llm
from backend.common.logger import get_logger

logger = get_logger("exam_node")
from backend.data.clients.minio import get_object_bytes
from backend.data.sql import session_scope


def _chinese_to_int(s: str) -> int:
    """
    把题号转成整数。

    优先按阿拉伯数字解析（'12' → 12）；否则查中文数字表（'三' → 3）。
    当前中文表只覆盖 1~10 的单个字符，查不到时兜底返回 1。
    """
    cn_map = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    try:
        return int(s)
    except ValueError:
        return cn_map.get(s, 1)


# 节点①：解析学员作答 Word 文件
def _sync_parse_word(word_bytes: bytes) -> list:
    """
    同步解析 Word 文件

    说明：这个函数像一台「状态机」：把 Word 一段一段（paragraph）往下扫，
    边扫边把内容归到「当前这道题」名下。靠 4 个状态变量记住扫到哪儿了：
        current_question     当前正在收集的题（dict）；None=还没遇到第一题
        current_answer_lines 当前题「普通答案」的行，逐行累积
        in_code_block        当前是否正处在代码块内部（True/False）
        code_buffer          当前代码块内的行，逐行累积
    每读到一段，先判断它是哪种「角色」，再据此更新状态：
        ① 空行              → 代码块内当作代码的一部分保留；块外忽略
        ② 题头(第X题/Q.X)   → 先把上一题「结算」存好，再开一道新题、清空状态
        ③ 代码围栏(三反引号) → 翻转 in_code_block；闭合时把 code_buffer 存为代码答案
        ④ 代码块内的行      → 原样塞进 code_buffer（不 strip，保留缩进）
        ⑤ 其他行            → 属于当前题的答案：跳过模板提示行、处理「答：」前缀

    「结算」= 遇到下一题题头、或文件读完时，把累积的答案 join 成 student_answer。
    """
    import re
    from io import BytesIO

    from docx import Document

    doc = Document(BytesIO(word_bytes))  # 直接从内存字节打开 Word 文档（不落盘）
    parsed_questions = []  # 最终结果：所有题组成的列表
    current_question = None  # 当前正在收集的题
    current_answer_lines = []  # 当前题「普通答案」累积的行
    in_code_block = False  # 是否正处在代码块内部
    code_buffer = []  # 当前代码块累积的行

    for para in doc.paragraphs:  # 逐段扫描整个文档（核心循环）
        para_text = para.text.strip()  # 该段文本（去掉首尾空白）
        # ① 角色：空行
        if not para_text:  # 这一段是空行
            if in_code_block:  # 若正处在代码块内
                code_buffer.append("")  # 空行也算代码的一部分，保留（维持代码格式）
            continue  # 块外的空行直接跳过，处理下一段

        # 先用正则判断这一段是不是「题目开头行」（仅支持 第x题 / Q.x / 题目x 三种格式）
        is_question_header = re.match(
            r"^(第?\s*[一二三四五六七八九十\d]+\s*[题、。.]|Q\.?\s*\d+|题目\s*\d+)",
            para_text,
            re.IGNORECASE,
        )
        # ② 角色：题头行 → 开一道新题
        if is_question_header:
            # 代码题在闭合围栏时存答案，此处只结算非代码题
            if current_question is not None:
                if not current_question.get("is_code"):
                    answer_text = (
                        "\n".join(code_buffer) if in_code_block else "\n".join(current_answer_lines)
                    )
                    current_question.student_answer = answer_text.strip()
                parsed_questions.append(current_question)

            # 从题头里提取题号：优先阿拉伯数字，其次中文数字（如「三」）
            match = re.search(r"[一二三四五六七八九十\d]+", para_text)
            q_no = _chinese_to_int(match.group()) if match else len(parsed_questions) + 1
            # 开一道新题，并把所有状态清零（开始为新题收集内容）
            current_question = ParsedQuestion(question_no=q_no, student_answer="")
            current_answer_lines = []  # 清空普通答案累积
            code_buffer = []  # 清空代码累积
            in_code_block = False  # 退出可能残留的代码块状态

        # ③ 角色：代码围栏行（以三反引号开头）→ 进入 / 退出代码块
        elif para_text.startswith("```"):
            in_code_block = not in_code_block
            if not in_code_block and current_question:  # 围栏闭合立刻结算代码答案
                current_question.student_answer = "\n".join(code_buffer).strip()
                current_question.is_code = True

        # ④ 角色：代码块内部的普通行
        elif in_code_block:
            code_buffer.append(para.text)
        # ⑤ 角色：其他行 → 都算「当前题」的答案内容
        elif current_question is not None:
            # 跳过纯模板提示行（可以自定义下面的列表）
            skip_prefixes = ["作答区", "请在此处"]
            if any(para_text.startswith(p) for p in skip_prefixes):
                pass
            else:
                # 处理「答：X」前缀：只取冒号后面的内容
                answer_prefixes = ["答：", "答:", "Answer:"]
                extracted = None
                for prefix in answer_prefixes:
                    if para_text.startswith(prefix):  # 这一行以「答：」开头
                        rest = para_text[len(prefix) :].strip()  # 取前缀后面的内容
                        if rest:  # 冒号后确实有内容（如「答：X」）
                            extracted = rest
                        break  # 不管冒号后有没有内容，都不再把整行加入
                if extracted is not None:  # 「答：X」这种行内带答案 → 收下提取结果
                    current_answer_lines.append(extracted)
                elif not any(para_text.startswith(p) for p in answer_prefixes):
                    current_answer_lines.append(
                        para_text
                    )  # 普通答案行（不以「答：」开头）→ 整行收下

    # 循环结束后，单独把「最后一题」结算（它后面没有题头来触发结算）
    if current_question is not None:
        if not current_question.is_code:
            answer_text = (
                "\n".join(code_buffer) if in_code_block else "\n".join(current_answer_lines)
            )
            current_question.student_answer = answer_text.strip()
        parsed_questions.append(current_question)

    return parsed_questions


async def parse_word_node(state: ExamState) -> dict:
    """
    解析学员提交的 Word 试卷文件，提取各题作答内容。

    文件持久化在 MinIO（word_minio_path 存对象 key），此处读取字节到内存直接解析，
    与 resume/download_pdf_node 同范式：全内存解析、不落盘。
    """
    object_key = state.get("word_minio_path") or state.get("word_file_path") or ""
    if not object_key:
        logger.error("parse_word.no_object_key")
        return {"parsed_questions": []}

    try:
        word_bytes = await get_object_bytes(object_key)
        parsed_questions = await asyncio.to_thread(_sync_parse_word, word_bytes)
        logger.debug(
            f"parse_word.done | key={object_key} | agent_questions_found={len(parsed_questions)}"
        )
        return {"parsed_questions": parsed_questions}
    except Exception as e:
        logger.exception(f"parse_word.failed | {e}")
        return {"parsed_questions": []}


# 节点②：加载试卷题目元数据
async def load_questions_meta_node(state: ExamState) -> dict:
    """
    从数据库加载试卷的完整题目元数据（含标准答案、得分点、知识点标签），
    与解析出的学员答案合并，覆盖写入 parsed_questions。

    合并原则：以「数据库题目」为主，学员答案只是补充。
    这样即使 Word 解析漏题/多题，卷面题目和分值仍以数据库为准。
    两道数据之间的关联键是 question_no（题号），不是列表下标。
    """
    exam_id = state["exam_id"]
    parsed = state["parsed_questions"]  # parse_word_node 的输出

    async with session_scope() as session:
        result = await session.execute(
            text(
                """
                SELECT id
                     , question_no
                     , question_type
                     , content
                     , correct_answer
                     , score
                     , knowledge_tag
                  FROM agent_questions
                 WHERE exam_id = :exam_id
                 ORDER BY question_no
                """
            ),
            {"exam_id": exam_id},
        )
        agent_questions = result.mappings().all()
        # 简答题加载得分点
        question_ids = [
            str(q["id"]) for q in agent_questions if q["question_type"] == "short_answer"
        ]
        scoring_points_rows = []
        if question_ids:
            param_names = [f":qid_{i}" for i in range(len(question_ids))]
            qid_params = {f"qid_{i}": qid for i, qid in enumerate(question_ids)}

            sp_result = await session.execute(
                text(
                    f"""
                    SELECT id
                         , question_id
                         , point_desc
                         , point_score
                    FROM scoring_points
                    WHERE question_id IN ({", ".join(param_names)})
                      AND is_active = TRUE
                    ORDER BY question_id, id
                    """
                ),
                qid_params,
            )
            scoring_points_rows = sp_result.mappings().all()

    # 按 question_id 聚合得分点
    sp_by_question: dict[str, list] = {}
    for sp in scoring_points_rows:
        qid = str(sp["question_id"])
        sp_by_question.setdefault(qid, []).append(
            ScoringPointItem(
                id=str(sp["id"]),
                desc=sp["point_desc"],
                score=sp["point_score"],
            )
        )

    # 以 DB 题目为主，合并解析结果
    parsed_by_no = {p.question_no: p for p in parsed}
    merged_questions = []

    for q in agent_questions:
        q_no = q["question_no"]
        merged_questions.append(
            ParsedQuestion(
                question_id=str(q["id"]),
                question_no=q_no,
                question_type=q["question_type"],
                content=q["content"],
                student_answer=(parsed_by_no.get(q_no) or ParsedQuestion()).student_answer,
                correct_answer=q["correct_answer"] or "",
                scoring_points=sp_by_question.get(str(q["id"]), []),
                full_score=q["score"],
                knowledge_tag=q["knowledge_tag"] or "",
            )
        )

    logger.info(f"load_questions_meta.done | {exam_id=} | total_questions={len(merged_questions)}")
    return {"parsed_questions": merged_questions}


# 第一轨：规则引擎（客观题）
def _normalize_answer(answer: str) -> str:
    """
    标准化答案字符串，消除大小写/空格/标点差异，使多选题选项顺序无关。

    处理步骤：
        1. 统一大写（A/a → A）
        2. 去除所有空格、中文逗号、英文逗号
           'A, B, C' → 'ABC'，'A，B，C' → 'ABC'
        3. 字符排序（多选题 'BA' 和 'AB' 视为等价）
           sorted('ABC') → ['A','B','C'] → 'ABC'
    """
    cleaned = answer.upper().replace(" ", "").replace("，", "").replace(",", "")
    return "".join(sorted(cleaned))


async def _run_objective_track(questions: list[ParsedQuestion]) -> list[ByQuestionItem]:
    """
    客观题规则批改。虽然声明为 async，内部没有 await，
    但保持 async 统一接口方便在 asyncio.gather 中与其他两轨并行。
    """
    results: list[ByQuestionItem] = []
    for q in questions:
        # 第一步：双方都做标准化（大写、去空格/逗号、字符排序），
        # 这样 'A, C, B' 和 'ABC' 会被视为同一个答案。
        student_ans = _normalize_answer(q.student_answer)
        correct_ans = _normalize_answer(q.correct_answer)
        # 第二步：完全相等即得分；客观题只有 0 分 / 满分两种结果。
        is_correct = student_ans == correct_ans

        results.append(
            ByQuestionItem(
                question_id=q.question_id,
                question_no=q.question_no,
                question_type=q.question_type,
                knowledge_tag=q.knowledge_tag,
                content=q.content,
                student_answer=q.student_answer,
                correct_answer=q.correct_answer,
                is_correct=is_correct,
                score=q.full_score if is_correct else 0,
                full_score=q.full_score,
                needs_review=False,  # 客观题不需要教师复核
                ai_feedback="正确" if is_correct else f"正确答案：{q.correct_answer}",
            )
        )

    return results


# 第二轨：大模型语义评分（简答题）
async def _review_one_subjective(q: ParsedQuestion) -> ByQuestionItem:
    """
    批改单道简答题，两步流程：

    第一步（Think）：让模型先逐条核对得分点，输出一段分析文字；
    第二步（Score）：把这段分析作为上下文，再要求模型按 SubjectiveReviewResult
                     结构输出分数和评语。
    这样做的原因见 prompts.py 文件头：先找证据再对照标准，分数更稳定、可解释。

    第一步失败不影响第二步（只是少了一段推理上下文）。
    """
    # 构造得分点描述文本
    scoring_points_text = (
        "\n".join([f"  {i + 1}. [{sp.score}分] {sp.desc}" for i, sp in enumerate(q.scoring_points)])
        or "  （无预设得分点，请综合评分）"
    )
    student_answer_text = q.student_answer or "（学员未作答）"

    # 第一步：推理分析
    reasoning_trace = ""
    try:
        think_prompt = (await resolve_prompt("subjective_think")).format(
            question_content=q["content"],
            scoring_points=scoring_points_text,
            student_answer=student_answer_text,
        )
        think_llm = await get_llm("exam")
        think_resp = await think_llm.ainvoke([HumanMessage(content=think_prompt)])
        reasoning_trace = str(think_resp.content).strip()
        logger.debug("subjective_think.done", question_no=q.get("question_no"))
    except Exception as e:
        logger.exception(f"subjective_think.failed | {e}")

    # 第二步：结构化评分
    think_context = f"\n\n【批改前分析】\n{reasoning_trace}" if reasoning_trace else ""
    review_prompt = (await resolve_prompt("subjective_review")).format(
        question_content=q.content,
        scoring_points=scoring_points_text,
        full_score=q.full_score,
        student_answer=student_answer_text,
    ) + think_context

    structured_llm = await get_structured_llm("exam", SubjectiveReviewResult)
    result: SubjectiveReviewResult = await structured_llm.ainvoke(
        [
            SystemMessage(content=await resolve_prompt("system")),  # 统一人设与批改原则
            HumanMessage(content=review_prompt),  # 评分任务 + 上一步的推理结论
        ]
    )
    return ByQuestionItem(
        question_id=q.question_id,
        question_no=q.question_no,
        question_type="short_answer",
        knowledge_tag=q.knowledge_tag,
        content=q.content,
        student_answer=q.student_answer,
        score=result.total_score,
        full_score=result.full_score,
        needs_review=result.confidence < 0.7,
        confidence=result.confidence,
        ai_feedback=result.overall_comment,
        point_results=result.point_results,
    )


async def _run_subjective_track(questions: list[ParsedQuestion]) -> list[ByQuestionItem]:
    """
    简答题批改，每 3 题一组并行处理。

    并行策略：
        把 N 道简答题切成 ⌈N/3⌉ 个组，组内 asyncio.gather 并行，
        组间顺序执行。目的是避免同时发起几十个 LLM 请求导致 API 限速。
    """
    if not questions:
        return []

    group_size = 3
    groups = [questions[i : i + group_size] for i in range(0, len(questions), group_size)]
    all_results: list[ByQuestionItem] = []
    for group in groups:
        group_results = await asyncio.gather(
            *[_review_one_subjective(q) for q in group],
            return_exceptions=True,
        )
        for q, result in zip(group, group_results):
            if isinstance(result, Exception):
                # 单题失败降级：标记 needs_review=True，不阻断整批
                logger.warning(
                    "subjective_track.question_failed",
                    question_id=q.question_id,
                    error=str(result),
                )
                all_results.append(
                    ByQuestionItem(
                        question_id=q.question_id,
                        question_no=q.question_no,
                        question_type="short_answer",
                        knowledge_tag=q.knowledge_tag,
                        content=q.content,
                        student_answer=q.student_answer,
                        score=0,
                        full_score=q.full_score,
                        needs_review=True,
                        confidence=0.0,
                        ai_feedback="AI 评分失败，已标记需教师人工批改",
                        point_results=[],
                    )
                )
            else:
                all_results.append(result)

    return all_results


# 第三轨：大模型评审代码题
async def _run_code_track(questions: list[ParsedQuestion]) -> list[ByQuestionItem]:
    """
    代码题批改入口：顺序逐题批改（代码题一般数量少，不必并行）。

    参数 questions：本卷里所有「代码题」的合并题目列表（来自 load 节点的合并结果，
                    已按题型筛选，这里只会收到 question_type == 'code' 的题）。
    返回：每道代码题的批改结果列表。
    """
    if not questions:  # 没有代码题（空列表）
        return []  # 直接返回空，省去后续循环
    results: list[ByQuestionItem] = []  # 收集每道题的批改结果
    for q in questions:  # 逐道代码题处理
        results.append(await _review_one_code(q))  # 调用单题批改，await 等它出结果
    return results  # 返回全部代码题的批改结果


async def _review_one_code(q: ParsedQuestion) -> ByQuestionItem:
    """
    批改「单道代码题」：交给大模型综合评估功能正确性 + 代码质量。

    参数 q：一道代码题的「合并题目」（load_questions_meta_node 产出），读取：
        q.question_id / q.question_no / q.content / q.student_answer /
        q.correct_answer / q.full_score / q.knowledge_tag
    返回：一道代码题的批改结果（ByQuestionItem）。
    """
    student_code = q.student_answer  # 取出学员代码
    reference_solution = q.correct_answer or ""  # 取出参考实现（缺省给空串）

    # 交给大模型评分：返回（逐条评语, 得分, 把握度）三元组
    feedback, score, confidence = await _llm_code_review(
        question_content=q.content,  # 题目内容
        student_code=student_code,  # 学员代码
        full_score=q.full_score,  # 该题满分（评分上限）
        reference_solution=reference_solution,  # 参考实现（对照标杆）
    )

    return ByQuestionItem(
        question_id=q.question_id,  # 题目 ID
        question_no=q.question_no,  # 题号
        question_type="code",  # 题型固定 code
        knowledge_tag=q.knowledge_tag,  # 知识点（缺省空串）
        content=q.content,  # 题目内容
        student_answer=student_code,  # 学员代码
        score=score,  # 本题最终得分（0~full_score）
        full_score=q.full_score,  # 本题满分
        confidence=confidence,  # LLM 评分把握度（0~1）
        needs_review=confidence < 0.7,  # 把握度低于 0.7 → 标记教师复核
        quality_feedback=feedback,  # LLM 逐条评语
        ai_feedback="\n".join(feedback),  # 评语拼成单个字符串，方便展示
    )


async def _llm_code_review(
    question_content: str,  # 题目内容
    student_code: str,  # 学员代码
    full_score: int,  # 该题满分（评分上限）
    reference_solution: str = "",  # 参考实现（默认空串）
) -> tuple[list[str], int, float]:
    """
    大模型综合评估代码：功能正确性 + 代码质量。

    返回一个三元组 (feedback, score, confidence)：
        feedback：  list[str]，逐条评语（功能正确性 + 四个质量维度）
        score：     int，得分，范围 0 ~ full_score
        confidence：float，LLM 自报的评分把握度，范围 0 ~ 1（越不确定越低）
    """
    # 用模板拼出完整 Prompt（把题目 / 参考实现 / 学员代码 / 满分填进去）
    prompt = (await resolve_prompt("code_review")).format(
        question=question_content,  # {question}
        reference_solution=reference_solution
        or "（无参考实现，仅按代码本身评估）",  # {reference_solution}，没有就填兜底语
        code=student_code or "（未提交代码）",  # {code}，没提交就填兜底语
        full_score=full_score,  # {full_score}：满分制
    )

    llm = await get_llm("exam")  # 从 llm_factory 取「代码评估」用的模型实例
    response = await llm.ainvoke(
        [  # 异步调用大模型
            SystemMessage(content=await resolve_prompt("system")),  # 系统提示（统一人设/规则）
            HumanMessage(content=prompt),  # 把上面拼好的 Prompt 作为用户消息
        ]
    )

    # 取出回复纯文本，并去掉模型可能多带的 ```json 代码围栏，方便 json.loads
    raw = str(response.content).strip().replace("```json", "").replace("```", "").strip()
    try:  # 解析可能失败，包 try
        data = json.loads(raw)  # 把回复解析成字典
        feedback = data.get("feedback", [])  # 取逐条评语列表（缺省空列表）
        score = min(int(data.get("score", 0)), full_score)  # 取分数，封顶到满分
        confidence = float(data.get("confidence", 0))  # 取把握度（缺省 0）
    except Exception as e:  # 模型没返回合法 JSON
        logger.exception(f"code_review.error | {e}")
        # JSON 解析失败时的降级：不崩，给 0 分 + 把握度 0（→ 必复核）+ 提示人工
        feedback = ["代码评估结果解析失败，请教师人工复核"]
        score = 0
        confidence = 0.0

    return feedback, score, confidence  # 返回（评语列表, 得分, 把握度）


# 节点③：三轨并行批改
async def run_three_tracks_node(state: ExamState) -> dict:
    """
    三轨并行批改节点。

    读取 state：
        state['parsed_questions']  6.4 合并好的完整题目列表（含 question_type）
    返回（会被 LangGraph 合并进 state）：
        objective_results / subjective_results / code_results  三轨各自的批改结果列表

    三轨：
        第一轨：规则引擎（客观题：单选/多选/判断）
        第二轨：LLM 语义评分（简答题，按 3 题一组并行）
        第三轨：大模型代码评估（代码题，顺序执行）

    asyncio.gather(return_exceptions=True)：
        某一轨抛异常不会中断其他轨，异常作为返回值处理；失败的轨结果置为空列表。
    """
    agent_questions = state["parsed_questions"]  # 取出合并好的题目列表

    # 按题型把题目分成三组，分别喂给三条轨
    objective_qs = [
        q
        for q in agent_questions
        if q.question_type  # 客观题：单选/多选/判断
        in ("single_choice", "multi_choice", "judge")
    ]
    subjective_qs = [q for q in agent_questions if q.question_type == "short_answer"]  # 简答题
    code_qs = [q for q in agent_questions if q.question_type == "code"]  # 代码题

    logger.info(  # 记一条日志：三轨各有多少题
        "three_tracks.start",
        objective=len(objective_qs),
        subjective=len(subjective_qs),
        code=len(code_qs),
    )

    # 三轨并行启动：gather 同时跑三个协程，任何一轨失败不影响其他轨
    raw = await asyncio.gather(
        _run_objective_track(objective_qs),  # 第一轨
        _run_subjective_track(subjective_qs),  # 第二轨
        _run_code_track(code_qs),  # 第三轨
        return_exceptions=True,  # 某轨抛异常→该位置返回异常对象而非崩溃
    )

    # 逐轨取结果：是异常就退化成空列表，正常就用返回值
    objective_results = raw[0] if not isinstance(raw[0], Exception) else []
    subjective_results = raw[1] if not isinstance(raw[1], Exception) else []
    code_results = raw[2] if not isinstance(raw[2], Exception) else []

    # 把失败的轨记到错误日志（不影响其余两轨的正常流程）
    for name, exc in zip(["objective", "subjective", "code"], raw):  # 轨名与返回值配对
        if isinstance(exc, Exception):
            logger.error(f"three_tracks.{name}_failed | {exc}")

    logger.debug("three_tracks.done")
    return {
        "objective_results": objective_results,
        "subjective_results": subjective_results,
        "code_results": code_results,
    }


# 节点④：汇总预批改结果
async def aggregate_results_node(state: ExamState) -> dict:
    """
    汇总节点：合并三轨结果，按题号排序，计算总分和需复核题数。

    读取 state：
        state['objective_results'] / ['subjective_results'] / ['code_results']  三轨结果
    返回：
        pre_review_summary  一个汇总字典（总分/满分/得分率/需复核数/逐题列表），
                            它是后续 HitL（6.9）展示给教师的核心数据结构。
    """
    all_results = (  # 三轨结果拼成一个大列表
        state.get("objective_results", [])  # 客观题结果（缺省空列表）
        + state.get("subjective_results", [])  # 简答题结果
        + state.get("code_results", [])  # 代码题结果
    )
    all_results.sort(key=lambda x: x.question_no)  # 按题号升序排（三轨混在一起，重排成卷面顺序）
    total_score = sum(r.score for r in all_results)  # 累加每题得分 = 总分
    full_score = sum(r.full_score for r in all_results)  # 累加每题满分 = 总满分
    score_rate = round(total_score / full_score, 4) if full_score > 0 else 0.0  # 得分率（防除零）
    needs_review_count = sum(1 for r in all_results if r.needs_review)  # 统计需复核的题数

    summary = PreReviewSummary(  # 组装汇总
        total_score=total_score,
        full_score=full_score,
        score_rate=score_rate,
        needs_review_count=needs_review_count,
        by_question=all_results,
    )

    logger.info(  # 记一条汇总日志
        "aggregate_results.done",
        total_score=total_score,
        full_score=full_score,
        score_rate=score_rate,
        needs_review=needs_review_count,
    )

    return {"pre_review_summary": summary}  # 返回汇总，写回 state


# 节点⑤：知识薄弱点分析
async def analyze_weak_points_node(state: ExamState) -> dict:
    """
    知识薄弱点分析节点。

    读取 state：
        state['pre_review_summary']['by_question']  逐题批改结果（来自 6.8.2 汇总）
        state['submission_id']                      提交记录 ID（仅用于日志）
    返回：
        weak_points          薄弱知识点列表（每个含 tag/wrong_count/question_nos/suggestion）
        weak_points_summary  整体评价文字

    两条路径：
        路径1：有 knowledge_tag 的失分题 → 按标签直接聚合（规则，不用 LLM）
        路径2：失分题整体交 LLM → 推断无标签题的知识点 + 为各薄弱点生成复习建议
    两路合并去重，按 wrong_count 降序排列。
    """
    raw_summary = state.get("pre_review_summary")
    summary = TypeAdapter(PreReviewSummary).validate_python(raw_summary) if raw_summary else None
    all_results = summary.by_question if summary else []  # 取逐题结果

    # 收集失分题（得分 < 满分就算失分，满分题不算薄弱）
    wrong_questions = [r for r in all_results if r.score < r.full_score]
    if not wrong_questions:  # 全部答对：没有薄弱点
        return {
            "weak_points": [],  # 空薄弱点列表
            "weak_points_summary": "本次试卷全部答对，表现优秀！",
        }
    # ── 路径1：有标签 → 按 knowledge_tag 直接聚合 ─────────────────
    tagged = [r for r in wrong_questions if r.knowledge_tag]  # 有知识点标签的失分题
    untagged = [r for r in wrong_questions if not r.knowledge_tag]  # 没有标签的失分题

    tagged_weak: dict[str, dict] = {}  # 标签 → 聚合结果
    for r in tagged:  # 逐道有标签的失分题
        tag = r.knowledge_tag  # 这道题的知识点
        if tag not in tagged_weak:  # 第一次见这个标签：建一个空聚合项
            tagged_weak[tag] = {
                "tag": tag,
                "wrong_count": 0,  # 该知识点错题数
                "total_count": 0,  # 该知识点涉及题数
                "question_nos": [],  # 涉及的题号
                "suggestion": "",  # 复习建议（稍后由 LLM 补）
            }
        tagged_weak[tag]["wrong_count"] += 1  # 错题数 +1
        tagged_weak[tag]["total_count"] += 1  # 题数 +1
        tagged_weak[tag]["question_nos"].append(r.question_no)  # 记下题号

    # ── 路径2：失分题整体交 LLM（推断知识点 + 生成 suggestion / summary）──
    llm_weak_points: list[dict] = []  # LLM 给出的薄弱点列表
    llm_summary = ""  # LLM 给出的整体评价

    agent_questions_for_llm = tagged + untagged  # 全部失分题都给 LLM（有标签的也要 LLM 补建议）
    if agent_questions_for_llm:  # 有失分题才调 LLM
        wrong_desc = "\n".join(
            [  # 把失分题拼成给 LLM 看的描述文本
                f"第{r.question_no}题（{r.question_type}，{r.score}/{r.full_score}分）："
                f"\n  题目：{r.content[:200]}"  # 题目（截断 200 字）
                f"\n  AI反馈：{r.ai_feedback[:150]}"  # AI 反馈（截断 150 字）
                for r in agent_questions_for_llm
            ]
        )

        prompt = (await resolve_prompt("weak_points_analysis")).format(
            wrong_questions=wrong_desc
        )  # 拼 Prompt
        logger.debug(f"len(prompt):{len(prompt)}")
        structured_llm = await get_structured_llm("exam", WeakPointsReport)  # 结构化输出模型

        try:  # LLM 可能失败，包 try
            report: WeakPointsReport = await structured_llm.ainvoke(
                [  # 调用 → 得到 WeakPointsReport
                    SystemMessage(content=await resolve_prompt("system")),
                    HumanMessage(content=prompt),
                ]
            )
            llm_weak_points = [wp.model_dump() for wp in report.weak_points]  # 转成 dict 列表
            llm_summary = report.overall_summary  # 整体评价
        except Exception as e:  # LLM 失败：降级，不崩
            logger.exception("analyze_weak_points.llm_failed", error=str(e))
            llm_summary = "薄弱点分析失败，请教师根据错题情况人工判断。"

    # ── 合并两路结果，去重 ────────────────────────────────────
    # 优先用规则聚合的结果（准确），LLM 只负责补 suggestion 和无标签题的知识点。
    merged_tags = set(tagged_weak.keys())  # 已被规则聚合的标签集合
    final_weak_points = []  # 最终薄弱点列表

    for llm_wp in llm_weak_points:  # 遍历 LLM 给的每个薄弱点
        tag = llm_wp.get("tag", "")
        if tag in tagged_weak:  # 这个标签规则已聚合 → 只取 LLM 的建议
            tagged_weak[tag]["suggestion"] = llm_wp.get("suggestion", "")
        elif tag not in merged_tags:  # 纯 LLM 推断出的新知识点（无标签题）
            final_weak_points.append(llm_wp)  # 直接收入
            merged_tags.add(tag)

    # 规则聚合的结果（已补上 suggestion）也加入最终列表
    for wp in tagged_weak.values():
        if not wp["suggestion"]:  # LLM 没给建议时给个兜底建议
            wp["suggestion"] = f"建议重点复习 {wp['tag']} 相关知识点。"
        final_weak_points.append(wp)

    # 按 wrong_count 降序排（错得最多的知识点排最前）
    final_weak_points.sort(key=lambda x: x.get("wrong_count", 0), reverse=True)

    logger.info(  # 记一条日志
        "analyze_weak_points.done",
        # submission_id=state['submission_id'],
        weak_count=len(final_weak_points),
    )

    return {  # 返回薄弱点 + 整体评价，写回 state
        "weak_points": [WeakPoint(**wp) for wp in final_weak_points],
        "weak_points_summary": llm_summary or "已完成薄弱点分析，请查看详情。",
    }


# 节点⑥：通知教师，更新提交状态
async def notify_teacher_node(state: ExamState) -> dict:
    """
    将提交状态推进到 pending_review，等待教师确认。

    职责：
        1. 更新 agent_exam_submissions.status = 'pending_review' #待审核
        2. 记录日志（生产环境可在此接入企业微信/钉钉推送）
    """
    async with session_scope() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    UPDATE agent_exam_submissions
                       SET status = 'pending_review'
                     WHERE id = :submission_id
                    """
                ),
                {"submission_id": state["submission_id"]},
            )

    # Todo: 真实通知渠道（钉钉/企业微信/WebSocket 推送）可在这里接入；当前只通过数据库状态表达「等待教师复核」。

    logger.debug("notify_teacher.done", submission_id=state["submission_id"])
    return {"teacher_notified": True}


# 节点⑦：Human-in-the-Loop 暂停点
async def teacher_review_node(state: ExamState) -> dict:
    """
    Human-in-the-Loop 核心节点。

    interrupt(display_data) 做两件事：
        1. 把 display_data 暴露给外部（教师可通过 GET 接口读取）
        2. 冻结图执行，State 自动保存到 MemorySaver

    图在此暂停，直到教师通过 POST /confirm 传入 Command(resume=decision) 恢复。
    恢复后，interrupt() 的返回值就是 decision（teacher_decision 字段）。
    """
    # 下面的内容作为 interrupt 的返回值暴露给外部，教师确认页上需要看到这些全部内容
    display_data = {
        "submission_id": state["submission_id"],
        "student_id": state["student_id"],
        "pre_review_summary": state.get("pre_review_summary", {}),
        "weak_points": state.get("weak_points", []),
        "weak_points_summary": state.get("weak_points_summary", ""),
        "message": "请检查 AI 预批改结果和知识薄弱点分析，确认无误后点击发布。",
    }

    # interrupt() 挂起图、checkpointer 存 state；外部 Command(resume=decision) 恢复后本节点从头重跑，故其前不能有副作用。
    teacher_decision = interrupt(display_data)

    logger.debug(
        f"teacher_review.resumed | submission_id={state['submission_id']} | action={teacher_decision.get('action', 'unknown')}"
    )
    return {"teacher_decision": teacher_decision}


# 节点⑧：合并教师修改
async def apply_teacher_decision_node(state: ExamState) -> dict:
    """
    将教师决策合并到批改结果中。

    approve：直接把 AI 分数作为最终分数
    modify： 按 modifications 列表覆盖指定题目的得分和评语
    """
    decision: dict = state.get("teacher_decision") or {}
    action = decision.get("action", "approve")
    modifications = decision.get("modifications", [])

    raw_summary = state.get("pre_review_summary")
    summary = TypeAdapter(PreReviewSummary).validate_python(raw_summary) if raw_summary else None
    all_results = list(summary.by_question) if summary else []

    # 每道题先用 AI 分数初始化 final_score（教师不改分时，最终分 = AI 分）
    for r in all_results:
        r.final_score = r.score

    # modify 时，按 question_id 找到对应题目，覆盖分数和评语。
    # 先建「question_id → 下标」索引，避免每条修改都线性扫描一遍列表。
    if action == "modify" and modifications:
        id_to_idx = {r.question_id: i for i, r in enumerate(all_results)}
        for mod in modifications:
            qid = mod.get("question_id")
            if qid in id_to_idx:  # 找不到对应题目的修改项直接忽略
                idx = id_to_idx[qid]
                if "new_score" in mod:
                    # 同时保留 AI 分（score）和教师分（teacher_score），
                    all_results[idx].teacher_score = mod["new_score"]
                    all_results[idx].final_score = mod["new_score"]
                if "comment" in mod:
                    all_results[idx].teacher_comment = mod["comment"]

    logger.debug(
        f"apply_teacher_decision.done | {action=} | modifications_count={len(modifications)}"
    )
    return {"final_results": all_results}


# 节点⑨：发布批改结果
async def publish_results_node(state: ExamState) -> dict:
    """
    将最终批改结果写入数据库，发布给学员。

    写入逻辑：
        agent_exam_reviews  ── 先删后插（幂等），每道题一行
        agent_exam_submissions ── 更新 status='published' + weak_points JSON

    整个写入过程放在同一个事务里（session.begin()）：
    任何一条 SQL 失败都会整体回滚，不会出现「部分题目已发布」的中间状态。
    幂等性由「按 submission_id + question_id 先删后插」保证：
    重复调用本节点不会产生重复批改记录。
    """
    final_results: list[ByQuestionItem] = TypeAdapter(list[ByQuestionItem]).validate_python(
        state.get("final_results", [])
    )
    submission_id = state["submission_id"]
    teacher_id = (state.get("teacher_decision") or {}).get("teacher_id", "")
    weak_points = state.get("weak_points", [])

    async with session_scope() as session:
        async with session.begin():
            for r in final_results:
                # 先删后插：避免重复发布时产生重复记录
                await session.execute(
                    text(
                        """
                        DELETE FROM agent_exam_reviews
                        WHERE submission_id = :submission_id
                          AND question_id   = :question_id
                        """
                    ),
                    {"submission_id": submission_id, "question_id": r["question_id"]},
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO agent_exam_reviews
                            (
                            id, submission_id, question_id, question_type,
                            knowledge_tag, student_answer,
                            ai_score, ai_feedback, ai_raw_result,
                            teacher_score, teacher_comment, final_score,
                            needs_review, reviewed_user_id, reviewed_at,
                            create_user_id, update_user_id
                            )
                        VALUES
                            (
                            :id, :submission_id, :question_id, :question_type,
                            :knowledge_tag, :student_answer,
                            :ai_score, :ai_feedback, :ai_raw_result,
                            :teacher_score, :teacher_comment, :final_score,
                            :needs_review, :reviewed_user_id, NOW(),
                            :create_user_id, :update_user_id
                            )
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "submission_id": submission_id,
                        "question_id": r.question_id,
                        "question_type": r.question_type,
                        "knowledge_tag": r.knowledge_tag,
                        "student_answer": r.student_answer,
                        "ai_score": r.score,
                        "ai_feedback": r.ai_feedback,
                        "ai_raw_result": json.dumps(r.model_dump()),
                        "teacher_score": r.teacher_score
                        if r.teacher_score is not None
                        else r.final_score,
                        "teacher_comment": r.teacher_comment or "",
                        "final_score": r.final_score,
                        "needs_review": r.needs_review,
                        "reviewed_user_id": teacher_id,
                        "create_user_id": teacher_id,
                        "update_user_id": teacher_id,
                    },
                )

            # 更新提交状态为已发布
            await session.execute(
                text(
                    """
                    UPDATE agent_exam_submissions
                       SET status = 'published'
                         , published_at = NOW()
                         , updated_at = NOW()
                         , weak_points = :weak_points
                         , weak_points_summary = :weak_points_summary
                     WHERE id = :submission_id
                    """
                ),
                {
                    "submission_id": submission_id,
                    "weak_points": json.dumps(
                        [wp.model_dump() if isinstance(wp, WeakPoint) else wp for wp in weak_points]
                    ),
                    "weak_points_summary": state.get("weak_points_summary", ""),
                },
            )

    total_final = sum(r.final_score for r in final_results)
    full_score = sum(r.full_score for r in final_results)

    logger.info(
        f"publish_results.done | {submission_id=} | {total_final=} | weak_points_count={len(weak_points)}"
    )
    return {
        "published": True,
        "structured_output": {
            "submission_id": submission_id,
            "final_score": total_final,
            "full_score": full_score,
            "score_rate": round(total_final / full_score, 4) if full_score else 0,
            "weak_points": weak_points,
            "weak_points_summary": state.get("weak_points_summary", ""),
            "published": True,
        },
    }
