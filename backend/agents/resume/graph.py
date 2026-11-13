"""简历评审工作流图：上传 → 下载 → 抽取 → 结构化 → 六维 → 问题 → 总结 → 落库。"""

from langgraph.graph import StateGraph, START, END

from backend.agents.resume.nodes import (
    upload_to_minio_node,
    download_pdf_node,
    extract_text_node,
    extract_structured_node,
    run_six_dimensions_node,
    diagnose_issues_node,
    generate_summary_node,
    save_results_node,
)
from backend.agents.resume.state import ResumeState


def build_resume_graph():
    """构建并编译简历审查 Agent 的状态图"""
    builder = StateGraph(ResumeState)  # type: ignore

    builder.add_node("upload_to_minio", upload_to_minio_node)  # type: ignore
    builder.add_node("download_pdf", download_pdf_node)  # type: ignore
    builder.add_node("extract_text", extract_text_node)  # type: ignore
    builder.add_node("extract_structured", extract_structured_node)  # type: ignore
    builder.add_node("run_six_dimensions", run_six_dimensions_node)  # type: ignore
    builder.add_node("diagnose_issues", diagnose_issues_node)  # type: ignore
    builder.add_node("generate_summary", generate_summary_node)  # type: ignore
    builder.add_node("save_results", save_results_node)  # type: ignore

    builder.add_edge(START, "upload_to_minio")
    builder.add_edge("upload_to_minio", "download_pdf")
    builder.add_edge("download_pdf", "extract_text")
    builder.add_edge("extract_text", "extract_structured")
    builder.add_edge("extract_structured", "run_six_dimensions")
    builder.add_edge("run_six_dimensions", "diagnose_issues")
    builder.add_edge("diagnose_issues", "generate_summary")
    builder.add_edge("generate_summary", "save_results")
    builder.add_edge("save_results", END)

    return builder.compile()


if __name__ == "__main__":
    graph = build_resume_graph()

    # 获得 Mermaid 代码
    print(graph.get_graph().draw_mermaid())

    # 绘制 PNG 工作流图
    graph.get_graph().draw_png("resume_graph.png")

    print("节点列表：", list(graph.nodes.keys()))
