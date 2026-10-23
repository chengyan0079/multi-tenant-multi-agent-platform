"""简历审查节点：解析/六维度评分/诊断/报告。"""
from __future__ import annotations

from backend.agents.resume.state import ResumeState
from backend.core.tracing import tracing
from backend.plugins.registry import PluginRegistry


async def parse_pdf(state: ResumeState) -> ResumeState:
    """PDF 解析→结构化提取。pdf_parse 能力缺失时降级为空结构。"""
    tracing.event("resume.parse_pdf")
    plugin_registry: PluginRegistry = _registry()
    tool = plugin_registry.get_tool("pdf_parse")
    structured: dict = {}
    if tool is not None:
        try:
            structured = await plugin_registry.call("pdf_parse", file_ref=state.get("file_ref", ""))
        except Exception:
            structured = {}
    return {"structured": structured}


# 六维度：并行 fan-out。每个节点只写自身维度分数，互不覆盖。
_DIMENSIONS = ["content", "structure", "match", "expression", "project", "education"]


async def _score_dimension(state: ResumeState, dim: str) -> ResumeState:
    tracing.event(f"resume.score.{dim}")
    # 占位评分：真实逻辑接 resume_scorer_* 插件（见 §15.3）
    return {"scores": {dim: 0.0}}


def make_scorer(dim: str):
    async def _node(state: ResumeState) -> ResumeState:
        return await _score_dimension(state, dim)

    return _node


async def diagnose(state: ResumeState) -> ResumeState:
    """六维度汇总→问题诊断。"""
    tracing.event("resume.diagnose")
    scores = state.get("scores", {})
    return {"diagnosis": f"六维度评分: {scores}"}


async def build_report(state: ResumeState) -> ResumeState:
    """整体评价/报告生成（落库在 api 层）。"""
    tracing.event("resume.report")
    return {"report": state.get("diagnosis", "")}


def _registry() -> PluginRegistry:
    from backend.app_state import app_state

    return app_state.plugin_registry  # type: ignore[return-value]
