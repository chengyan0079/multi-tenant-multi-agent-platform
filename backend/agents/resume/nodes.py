"""
nodes - 工作流节点

Author: 骆昊
Version: 0.0.1
"""
import asyncio

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser

from backend.agents.resume.prompts import *
from backend.agents.resume.state import *
from backend.common.logger import get_logger
from backend.common.llm.llm_factory import

logger = get_logger("resume.nodes")

async def upload_to_minio_node(state: ResumeState) -> dict:
    """文件上传"""
    logger.info('upload_to_minio.skip', review_id=state['review_id'], reason='local_mode')
    return {}


async def download_pdf_node(state: ResumeState) -> dict:
    """文件下载"""
    logger.info('download_pdf.skip', review_id=state['review_id'], reason='local_file_exists')
    return {}


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


async def extract_structured_node(state: ResumeState) -> dict:
    """用大模型把原始文本提取成结构化简历"""
    raw_text = state['raw_text']
    # 超长截断 - 这里的字面常量最好放到配置文件中（方便维护）
    text_for_llm = raw_text[:4000] if len(raw_text) > 4000 else raw_text
    prompt = EXTRACT_STRUCTURED_PROMPT.format(resume_text=text_for_llm)

    structured_llm = get_structured_llm('resume', ResumeStructured)

    structured = None
    for attempt in range(2):
        try:
            structured = await structured_llm.ainvoke([
                SystemMessage(content=SYSTEM_PROMPT),
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
        """评审单个维度"""
        # 通过 dim_info['name'] 获取评审维度的名字，再获取对应的提示词
        prompt_template = DIMENSION_REVIEW_PROMPTS[dim_info['name']]

        prompt = prompt_template.format(
            structured_summary=structured_summary,
            focus=dim_info['focus'],
        )

        # 如果调用大模型评分失败就返回默认分数
        dim_score = _empty_dimension_score(dim_info)
        for attempt in range(2):
            try:
                structured_llm = get_structured_llm('resume', DimensionScore)
                dim_score = await structured_llm.ainvoke([
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ])  # type: DimensionScore
                dim_score.dimension = dim_info['name']
                dim_score.weight = dim_info['weight']
            except Exception as e:
                if attempt < 2:
                    logger.warning(f'six_dimensions.dimension_retry | {e}')
                    await asyncio.sleep(1)
                else:
                    logger.warning('six_dimensions.dimension_failed')
                    raise
        return dim_score

    # 通过 asyncio.gather 六个协程对象分别给六个维度打分最后获得一个列表
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
        think_prompt = DIAGNOSE_THINK_PROMPT.format(
            dimension_scores_summary=dimension_scores_summary,
            raw_issues=raw_issues_text,
        )
        think_llm = get_llm('resume')
        chain = think_llm | StrOutputParser()
        reasoning_trace = await chain.ainvoke([HumanMessage(content=think_prompt)])
        logger.debug(f'diagnose_think.done | scores={len(dimension_scores)}')
    except Exception as e:
        logger.warning(f'diagnose_think.failed | {e}')
        raise

    think_context = f'\n\n【诊断前宏观分析】\n{reasoning_trace}' if reasoning_trace else ''

    prompt = DIAGNOSE_ISSUES_PROMPT.format(
        resume_text=raw_text[:4000],
        structured_summary=structured_summary,
        raw_issues=raw_issues_text,
    ) + think_context

    try:
        structured_llm = get_structured_llm('resume', IssueList)
        result = await structured_llm.ainvoke([
            SystemMessage(content=SYSTEM_PROMPT),
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
    prompt = GENERATE_SUMMARY_PROMPT.format(
        structured_summary=structured_summary,
        scores_summary=scores_text,
        weighted_score=round(weighted_score, 1),
        high_issues=high_issues_text,
        target_position=target_position,
    )

    structured_llm = get_structured_llm('resume', ResumeSummary)

    resume_summary = None
    for attempt in range(2):
        try:
            resume_summary = await structured_llm.ainvoke([
                SystemMessage(content=SYSTEM_PROMPT),
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


# async def save_results_node(state: ResumeState) -> dict:
#     """把完整结果写入 resume_reviews，清理临时文件"""
#     review_id = state['review_id']
#
#     structured_output = {
#         'review_id': review_id,
#         'student_id': state['student_id'],
#         'structured': state.get('structured'),
#         'weighted_score': state.get('weighted_score', 0),
#         'dimension_scores': state.get('dimension_scores', []),
#         'issues': state.get('issues', []),
#         'summary': state.get('summary'),
#     }
#
#     async with async_session_factory() as session:
#         async with session.begin():
#             await session.execute(
#                 text(
#                     '''
#                     UPDATE resume_reviews
#                        SET structured_data = :structured_data,
#                            scores          = :scores,
#                            issues          = :issues,
#                            summary         = :summary,
#                            status          = 'done',
#                            updated_at      = NOW()
#                      WHERE id = :review_id'''
#                 ),
#                 {
#                     'structured_data': json.dumps(state.get('structured'), ensure_ascii=False),
#                     'scores': json.dumps(
#                         {
#                             'dimension_scores': state.get('dimension_scores', []),
#                             'weighted_score': state.get('weighted_score', 0)
#                         },
#                         ensure_ascii=False
#                     ),
#                     'issues':  json.dumps(state.get('issues', []), ensure_ascii=False),
#                     'summary': json.dumps(state.get('summary'), ensure_ascii=False),
#                     'review_id': review_id,
#                 },
#             )
#             logger.info(f'save_results.db_written | review_id={review_id}')
#
#     local_path = state.get('pdf_local_path', '')
#     if local_path and os.path.exists(local_path):
#         os.remove(local_path)
#         logger.info(f'save_results.tmp_cleaned | path = {local_path}')
#
#     return {'fallback_used': False, 'structured_output': structured_output}


async def main():
    resume_state = ResumeState(pdf_local_path='程岩-Agent开发工程师-11年.pdf')
    # 节点3
    result = await extract_text_node(state=resume_state)
    print(f'提取内容：{result}')
    resume_state.update(result)
    # 节点4
    result = await extract_structured_node(state=resume_state)
    print(f'结构化简历：{result}')
    resume_state.update(result)
    # 节点5
    result = await run_six_dimensions_node(state=resume_state)
    print(f'六维度评审：{result}')
    resume_state.update(result)
    # 节点6
    result = await diagnose_issues_node(state=resume_state)
    print(f'汇总六维度问题：{result}')
    resume_state.update(result)
    # 节点7
    result = await generate_summary_node(state=resume_state)
    resume_state.update(result)
    print(f'整体评价：{result}')


if __name__ == '__main__':
    setup_logger(console_level='DEBUG')
    asyncio.run(main())
