"""
nodes - 简历评审工作流节点

"""
import asyncio
import os
import tempfile

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from pydantic import TypeAdapter
from sqlalchemy import text

from backend.agents.resume.prompts import *
from backend.agents.resume.state import *
from backend.common.llm.llm_factory import get_structured_llm, get_llm
from backend.common.logger import get_logger, setup_logging
from backend.data.clients.minio import get_storage
from backend.data.sql import session_scope
from backend.security.rbac import Business

logger = get_logger("resume_node")
current_agent_type = Business.RESUME

def _read_file_bytes(path: str) -> bytes:
    """同步读取本地文件字节（供 asyncio.to_thread 调用）。"""
    with open(path, "rb") as f:
        return f.read()


async def upload_to_minio_node(state: ResumeState) -> dict:
    """将 PDF 上传到 MinIO（幂等：pdf_minio_path 已存在则跳过）。

    备注：当前由 API 层在收到上传文件时已完成上传并写入 pdf_minio_path，故节点通常直接跳过；
    保留此节点以支持不经 API、直接经 Orchestrator 触发的场景。
    """
    if state.get("pdf_minio_path"):
        return {}
    local = state.get("pdf_local_path")
    if not local:
        logger.warning("upload_to_minio.skip", review_id=state.get("review_id"), reason="no_local_file")
        return {}
    review_id = state.get("review_id", "")
    tenant_id = state.get("tenant_id", "")
    user_id = state.get("user_id", "")
    key = f"resumes/{tenant_id}/{user_id}/{review_id}.pdf"
    try:
        storage = await get_storage()
        data = await asyncio.to_thread(_read_file_bytes, local)
        await asyncio.to_thread(storage.put_bytes, key, data, content_type="application/pdf")
        logger.info("upload_to_minio.done", review_id=review_id, key=key)
        return {"pdf_minio_path": key}
    except Exception as e:
        logger.error(f"upload_to_minio.failed | {e}")
        raise


async def download_pdf_node(state: ResumeState) -> dict:
    """从 MinIO 下载 PDF 到本地临时文件，供 pymupdf 解析。"""
    key = state.get("pdf_minio_path")
    if not key:
        raise ValueError("download_pdf_node: pdf_minio_path 缺失")
    try:
        storage = await get_storage()
        data = await asyncio.to_thread(storage.get_bytes, key)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp.write(data)
        tmp.close()
        logger.info("download_pdf.done", review_id=state.get("review_id"), path=tmp.name)
        return {"pdf_local_path": tmp.name}
    except Exception as e:
        logger.error(f"download_pdf.failed | {e}")
        raise


def _sync_extract_text(pdf_path: str) -> dict:
    import pymupdf

    pages = pymupdf.open(pdf_path)
    page_count = len(pages)
    all_text_parts = []

    for page in pages:
        # 每个 block 都是一个七元组 - (x0, y0, x1, y1, text, block_no, block_type)
        blocks = pymupdf.utils.get_text(page, 'blocks')
        # 将文本块抽取出来保存在列表中
        text_blocks = [b for b in blocks if b[6] == 0]
        if not text_blocks:
            continue

        # 如果抽取到文本块 ---> 判定是否双栏设计 ---> 给块排序（从左到右，从上到下） ---> 按顺序抽取文本
        page_width = page.rect.width
        midpoint = page_width / 2

        # 把左右边栏的块分别放到两个列表中
        left_blocks = [b for b in text_blocks if b[2] < midpoint + 20]
        right_blocks = [b for b in text_blocks if b[0] >= midpoint - 20]

        # 双栏布局判定标准：左栏至少有 2 个文本块、右栏至少有 2 个文本块，且右栏的文本块数量占总文本块的比例超过 30%
        # 说明：这个可以根据具体情况进行调整（这段代码属于硬代码，不够优雅但对我来说暂时也找不到更好的做法了）
        is_two_column = (
                len(left_blocks) >= 2 and len(right_blocks) >= 2
                and len(right_blocks) / max(len(text_blocks), 1) > 0.3
        )

        if is_two_column:
            left_sorted = sorted(left_blocks, key=lambda b: b[1])
            right_sorted = sorted(right_blocks, key=lambda b: b[1])
            page_text = (
                    '\n'.join(b[4].strip() for b in left_sorted if b[4].strip()) +
                    '\n' +
                    '\n'.join(b[4].strip() for b in right_sorted if b[4].strip())
            )
        else:
            sorted_blocks = sorted(text_blocks, key=lambda b: b[1])
            page_text = '\n'.join(b[4].strip() for b in sorted_blocks if b[4].strip())

        all_text_parts.append(page_text)

    pages.close()

    raw_text = '\n\n---PAGE BREAK---\n\n'.join(all_text_parts)
    return {'raw_text': raw_text, 'page_count': page_count}


async def extract_text_node(state: ResumeState) -> dict:
    """提取文本（异步操作 - 通过线程池跑执行解析避免阻塞事件循环）"""
    pdf_path = state['pdf_local_path']
    try:
        result = await asyncio.to_thread(_sync_extract_text, pdf_path)
        raw_text, page_count = result['raw_text'], result['page_count']

        if len(raw_text.strip()) < 200:
            logger.warning(f'extract_text.text_too_short | length={len(raw_text.strip())}')

        logger.debug(f'extract_text.done | page={page_count}, length={len(raw_text)}')
        return result
    except Exception as e:
        logger.error(f'extract_text.failed | {e}')
        raise
    finally:
        # 清理 download_pdf_node 创建的临时 PDF；仅当确属系统临时目录，避免误删用户传入的真实本地文件
        if pdf_path and os.path.commonpath([tempfile.gettempdir(), os.path.abspath(pdf_path)]) == tempfile.gettempdir():
            try:
                os.remove(pdf_path)
            except OSError as exc:
                logger.warning(f'extract_text.temp_cleanup_failed | {exc}')


async def extract_structured_node(state: ResumeState) -> dict:
    """用大模型把原始文本提取成结构化简历"""
    raw_text = state['raw_text']
    # 超长截断 - 这里的字面常量最好放到配置文件中（方便维护）
    text_for_llm = raw_text[:4000] if len(raw_text) > 4000 else raw_text
    prompt = (await resolve_prompt("extract_structured")).format(resume_text=text_for_llm)

    structured_llm = get_structured_llm(current_agent_type, ResumeStructured)

    structured = None
    for attempt in range(2):
        try:
            structured = await structured_llm.ainvoke([
                SystemMessage(content=await resolve_prompt("system")),
                HumanMessage(content=prompt),
            ])
            if not structured:
                raise ValueError('structured output returned None')
            break
        except Exception as e:
            if attempt < 2:
                logger.warning(f'extract_structured.retry | {e}')
                await asyncio.sleep(1)
            else:
                logger.warning(f'extract_structured.failed | {e}')
                raise

    if not structured:
        structured = ResumeStructured(name='未能提取')

    logger.debug(f'extract_structured.done | name={structured.name} | projects={len(structured.projects)}')
    return {'structured': structured}


# 评审的六个维度的定义
SIX_DIMENSIONS = [
    {
        'name': '项目深度',
        'weight': 0.3,
        'focus': '项目描述是否有量化数据、技术选型理由、个人贡献、难点解决'
    },
    {
        'name': '技术匹配度',
        'weight': 0.25,
        'focus': '技术栈是否与目标岗位匹配，技能描述是否有层次（熟练/了解/掌握）'
    },
    {
        'name': '表达规范性',
        'weight': 0.15,
        'focus': '动词开头、STAR 结构、无错别字、无主语省略歧义'
    },
    {
        'name': '简历结构',
        'weight': 0.15,
        'focus': '模块完整性、排版逻辑、信息密度、重要内容是否放前面'
    },
    {
        'name': '量化程度',
        'weight': 0.10,
        'focus': '性能指标、用户量、优化幅度等量化数据的使用情况'
    },
    {
        'name': '真实可信度',
        'weight': 0.05,
        'focus': '表述是否夸大、技术深度描述是否与经验年限匹配、时间线是否合理'
    },
]


# 指定维度评审失败时的降级处理的结果
def _empty_dimension_score(dim_info: dict) -> DimensionScore:
    return DimensionScore(
        dimension=dim_info['name'],
        score=60,
        weight=dim_info['weight'],
        issues=['该维度评审失败，建议人工复核'],
        suggestions=[],
    )


async def run_six_dimensions_node(state: ResumeState) -> dict:
    """六维度并行评审"""
    structured: ResumeStructured | None = state.get('structured')
    structured_summary = structured.model_dump_json() if structured else ''

    async def review_one_dimension(dim_info: dict) -> DimensionScore:
        """评审单个维度（失败重试，最终失败降级为默认分，不中断整体评审）"""
        prompt_template = await resolve_dimension_prompt(dim_info['name'])

        prompt = prompt_template.format(
            structured_summary=structured_summary,
            focus=dim_info['focus'],
        )

        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                structured_llm = get_structured_llm(current_agent_type, DimensionScore)
                dim_score = await structured_llm.ainvoke([
                    SystemMessage(content=await resolve_prompt("system")),
                    HumanMessage(content=prompt),
                ])  # type: DimensionScore
                dim_score.dimension = dim_info['name']
                dim_score.weight = dim_info['weight']
                return dim_score
            except Exception as e:
                logger.warning(
                    f'six_dimensions.dimension_retry | dim={dim_info["name"]} '
                    f'attempt={attempt + 1}/{max_attempts} | {e}'
                )
                await asyncio.sleep(1)
        # 全部重试仍失败 → 降级为默认分（不抛出，避免单维度抖动拖垮整份评审）
        logger.error(f'six_dimensions.dimension_failed | dim={dim_info["name"]} | 降级为默认分')
        return _empty_dimension_score(dim_info)

    # 通过 asyncio.gather 并行给六个维度打分；单维度失败已在内部重试并降级，不再吞异常
    tasks = [review_one_dimension(dim_info) for dim_info in SIX_DIMENSIONS]
    dimension_scores = await asyncio.gather(*tasks)

    # 计算带权重的总分数
    weighted_score = sum(d.score * d.weight for d in dimension_scores)
    logger.debug('six_dimensions.done')

    return {
        'dimension_scores': dimension_scores,
        'weighted_score': round(weighted_score, 2),
    }


async def diagnose_issues_node(state: ResumeState) -> dict:
    """汇总六维度问题，前置推理后生成带优先级的诊断清单"""
    dimension_scores = state.get('dimension_scores', [])
    raw_text = state['raw_text']
    structured: ResumeStructured | None = state.get('structured')
    structured_summary = structured.model_dump_json() if structured else ''

    all_raw_issues = []
    # 将各个维度的各种问题统一收集到列表中
    for dim in dimension_scores:
        for issue_text in dim.issues:
            all_raw_issues.append(f'[{dim.dimension}] {issue_text}')

    raw_issues_text = '\n'.join(f'- {i}' for i in all_raw_issues) or '（暂无）'

    try:
        dimension_scores_summary = '\n'.join(
            f'- {dim_score.dimension}：{dim_score.score}分 — 问题：{', '.join(dim_score.issues)}'
            for dim_score in dimension_scores
        )
        think_prompt = (await resolve_prompt("diagnose_think")).format(
            dimension_scores_summary=dimension_scores_summary,
            raw_issues=raw_issues_text,
        )
        think_llm = get_llm(current_agent_type)
        chain = think_llm | StrOutputParser()
        reasoning_trace = await chain.ainvoke([HumanMessage(content=think_prompt)])
        logger.debug(f'diagnose_think.done | scores={len(dimension_scores)}')
    except Exception as e:
        logger.warning(f'diagnose_think.failed | {e}')
        raise

    think_context = f'\n\n【诊断前宏观分析】\n{reasoning_trace}' if reasoning_trace else ''
    prompt_template = await resolve_prompt("diagnose_issues")
    prompt = prompt_template.format(
        resume_text=raw_text[:4000],
        structured_summary=structured_summary,
        raw_issues=raw_issues_text,
    ) + think_context

    try:
        structured_llm = get_structured_llm(current_agent_type, IssueList)
        result = await structured_llm.ainvoke([
            SystemMessage(content=await resolve_prompt("system")),
            HumanMessage(content=prompt),
        ])  # type: IssueList
        issues = result.items
    except Exception as e:
        logger.warning(f'diagnose_issues.failed | {e}')
        issues = [
            IssueItem(
                priority='medium',
                dimension=dim_score.dimension,
                description=issue,
                location='简历全文',
                suggestion='请参考评审建议修改'
            )
            for dim_score in dimension_scores
            for issue in dim_score.issues
        ]

    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    # 列表就地排序操作（按照问题优先级排序）
    issues.sort(key=lambda x: priority_order.get(x.priority, 2))
    logger.debug(f'diagnose_issues.done | issues={len(issues)} | high={sum(i.priority == 'high' for i in issues)}')
    return {'issues': issues}


async def generate_summary_node(state: ResumeState) -> dict:
    """综合结构化信息、六维度评分、问题清单，生成面向学员的整体评价"""
    structured: ResumeStructured | None = state.get('structured')
    structured_summary = structured.model_dump_json() if structured else ''
    dimension_scores = state.get('dimension_scores', [])
    issues = state.get('issues', [])
    weighted_score = state.get('weighted_score', 0.0)

    high_issues = [item.description for item in issues if item.priority == 'high']
    high_issues_text = '\n'.join(f'- {i}' for i in high_issues) or '（无高优先级问题）'

    scores_text = '\n'.join(
        f'- {dim_score.dimension}：{dim_score.score}分（权重{dim_score.weight:.0%}）'
        for dim_score in dimension_scores
    )

    target_position = getattr(structured, 'target_position', '程序员')
    prompt = (await resolve_prompt("generate_summary")).format(
        structured_summary=structured_summary,
        scores_summary=scores_text,
        weighted_score=round(weighted_score, 1),
        high_issues=high_issues_text,
        target_position=target_position,
    )

    structured_llm = get_structured_llm(current_agent_type, ResumeSummary)

    resume_summary = None
    for attempt in range(2):
        try:
            resume_summary = await structured_llm.ainvoke([
                SystemMessage(content=await resolve_prompt("system")),
                HumanMessage(content=prompt),
            ])
            break
        except Exception as e:
            if attempt < 2:
                logger.warning(f'generate_summary.retry | {e}')
                await asyncio.sleep(1)
            else:
                logger.warning(f'generate_summary.failed | {e}')
                raise

    if not resume_summary:
        resume_summary = ResumeSummary(**{
            'highlights': ['简历内容已完整提交'],
            'core_improvements': high_issues[:2] if high_issues else ['请参考各维度建议修改'],
            'overall_comment': f'综合评分 {round(weighted_score, 1)} 分，请参考各维度详细反馈。',
            'fit_assessment': '与目标岗位匹配度评估暂不可用',
        })

    logger.debug(f'generate_summary.done | highlights={len(resume_summary.highlights)}')
    return {'summary': resume_summary}


async def save_results_node(state: ResumeState) -> dict:
    """把完整结果写入 agent_resume_reviews 表"""
    review_id = state['review_id']
    structured = state.get('structured') or ResumeStructured(name='未知')
    structured_data = structured.model_dump_json(ensure_ascii=False)
    scores_adapter = TypeAdapter(list[DimensionScore])
    dimension_scores_data = scores_adapter.dump_json(state.get('dimension_scores', []), ensure_ascii=False).decode('utf-8')
    issues_adapter = TypeAdapter(list[IssueItem])
    issues_data = issues_adapter.dump_json(state.get('issues', []), ensure_ascii=False).decode('utf-8')
    summary = state.get('summary') or ResumeSummary()
    summary_data = summary.model_dump_json(ensure_ascii=False)
    weighted_score = state.get('weighted_score', 0.0)

    structured_output = {
        'review_id': review_id,
        'user_id': state['user_id'],
        'tenant_id': state.get('tenant_id'),
        'structured': structured_data,
        'weighted_score': weighted_score,
        'dimension_scores': dimension_scores_data,
        'issues': issues_data,
        'summary': summary_data,
    }

    async with session_scope() as session:
        async with session.begin():
            await session.execute(
                text(
                    '''
                    UPDATE agent_resume_reviews
                       SET structured_data = :structured_data
                         , weighted_score  = :weighted_score
                         , scores          = :scores
                         , issues          = :issues
                         , summary         = :summary
                         , status          = 'done'
                         , update_user_id  = :update_user_id
                         , update_tenant_id = :update_tenant_id
                     WHERE id = :review_id'''
                ),
                {
                    'structured_data': structured_data,
                    'weighted_score': weighted_score,
                    'scores': dimension_scores_data,
                    'issues':  issues_data,
                    'summary': summary_data,
                    'update_user_id': state['user_id'],
                    'update_tenant_id': state.get('tenant_id'),
                    'review_id': review_id,
                },
            )
            logger.debug(f'save_results.db_written | review_id={review_id}')
    return {'fallback_used': False, 'structured_output': structured_output}


async def main():
    import uuid6

    review_user_id, user_id, resume_file_path = str(uuid6.uuid7()), 'student01', '个人简历-荤.pdf'
    # 工作流初始状态
    resume_state =             ResumeState(
        review_id=review_user_id,
        user_id=user_id,
        pdf_local_path=resume_file_path
    )
    # 节点3
    result = await extract_text_node(state=resume_state)
    resume_state.update(result)
    # 节点4
    result = await extract_structured_node(state=resume_state)
    resume_state.update(result)
    # 节点5
    result = await run_six_dimensions_node(state=resume_state)
    resume_state.update(result)
    # 节点6
    result = await diagnose_issues_node(state=resume_state)
    resume_state.update(result)
    # 节点7
    result = await generate_summary_node(state=resume_state)
    resume_state.update(result)
    # 节点8
    result = await save_results_node(state=resume_state)
    print(result)


if __name__ == '__main__':
    setup_logging(level='DEBUG')
    asyncio.run(main())
