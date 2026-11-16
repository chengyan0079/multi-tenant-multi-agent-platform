# -*- coding: utf-8 -*-
"""生成「统一咨询父图 + 各 agent 子图」调用关系 PNG。

输出: docs/graphs/unified_agent_orchestration.png
"""
from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

BRAND = "#3b5bdb"
BRAND_LIGHT = "#eef2ff"
ACCENT = "#13b5b1"
GOLD = "#d48806"
RED = "#cf1322"
GRAY = "#8c8c8c"

fig, ax = plt.subplots(figsize=(20, 12), dpi=150)
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")


def box(
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    *,
    fc: str = "#ffffff",
    ec: str = BRAND,
    fs: int = 10,
    bold: bool = False,
    ls: str = "-",
    lw: float = 1.4,
) -> tuple[float, float]:
    p = FancyBboxPatch(
        (x - w / 2, y - h / 2),
        w,
        h,
        boxstyle="round,pad=0.25,rounding_size=0.8",
        linewidth=lw,
        edgecolor=ec,
        facecolor=fc,
        linestyle=ls,
        zorder=3,
    )
    ax.add_patch(p)
    ax.text(
        x,
        y,
        text,
        ha="center",
        va="center",
        fontsize=fs,
        color="#1a2340" if fc != BRAND else "#ffffff",
        fontweight="bold" if bold else "normal",
        zorder=4,
        linespacing=1.35,
    )
    return x, y


def arrow(
    p1: tuple[float, float],
    p2: tuple[float, float],
    *,
    color: str = BRAND,
    ls: str = "-",
    style: str = "-|>",
    rad: float = 0.0,
    lw: float = 1.3,
    label: str | None = None,
    label_dx: float = 1.2,
) -> None:
    a = FancyArrowPatch(
        p1,
        p2,
        arrowstyle=style,
        mutation_scale=14,
        linewidth=lw,
        color=color,
        linestyle=ls,
        connectionstyle=f"arc3,rad={rad}",
        zorder=2,
        shrinkA=4,
        shrinkB=4,
    )
    ax.add_patch(a)
    if label:
        mx = (p1[0] + p2[0]) / 2 + label_dx
        my = (p1[1] + p2[1]) / 2
        ax.text(mx, my, label, fontsize=8, color=color, style="italic", zorder=5)


def cluster(x: float, y: float, w: float, h: float, title: str, color: str) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.4,rounding_size=1.2",
            linewidth=1.6,
            edgecolor=color,
            facecolor=color + "10",
            linestyle="--",
            zorder=1,
        )
    )
    ax.text(
        x + 0.8,
        y + h - 1.1,
        title,
        fontsize=12,
        color=color,
        fontweight="bold",
        zorder=5,
    )


# ---------------- 标题 ----------------
ax.text(
    50,
    98.4,
    "统一咨询编排：父图 + 各 Agent 子图（代码级子图调用，独立 thread_id 分区）",
    ha="center",
    va="center",
    fontsize=16,
    fontweight="bold",
    color="#1a2340",
)

# ---------------- 父图 ----------------
cluster(2, 12, 26, 82, "UnifiedGraph（父图 / 薄图）", BRAND)
p1 = box(15, 88, 22, 5.5, "SSE 入口\nPOST /unified/chat/stream", fc=BRAND, fs=9.5, bold=True)
p2 = box(15, 78, 22, 5.5, "意图识别（规则固定 5 类）\nsingle / parallel / sequential / clarify", fs=9)
p3 = box(15, 68, 22, 6, "RoutingDecision\nlabel / agent_type / execution_mode", fs=9)
p4 = box(15, 56, 22, 7, "AgentAdapter\nto_subgraph_input / stream / dispatch\nfrom_subgraph_output", fs=9, ec=ACCENT)
p5 = box(15, 45, 22, 5.5, "meta 事件\n出处 / 置信度 / 耗时 / tokens", fs=9)
p6 = box(15, 34, 22, 5.5, "append_turn\nagent_unified_turn（唯一历史源）", fs=9)
p7 = box(15, 23, 22, 5, "SSE 输出\ntoken / progress / meta / done", fs=9)
p8 = box(15, 15.5, 22, 4.5, "thread_id 分区（父）\nt{tenant}:u{user}:{session}", fs=8, ec=GRAY, ls=":")

arrow((15, 85.2), (15, 80.8))
arrow((15, 75.2), (15, 71.2))
arrow((15, 65), (15, 59.6))
arrow((15, 52.5), (15, 47.8))
arrow((15, 42.2), (15, 36.8))
arrow((15, 31.2), (15, 25.6))

# ---------------- 子图：qa ----------------
cluster(34, 74, 64, 20, "qa 子图（问答 / RAG）", ACCENT)
qa1 = box(43, 87, 15, 5.6, "classify_query", fs=9)
qa2 = box(43, 79.5, 15, 5.2, "hyde / multi_query\n（按类型分支）", fs=8.5)
qa3 = box(61, 87, 15, 5.6, "retrieve\n混合召回 + BGE 精排", fs=9)
qa4 = box(61, 79.5, 15, 5.2, "grade_relevance\n（置信度）", fs=9)
qa5 = box(80, 87, 16, 5.6, "generate_rag / direct\n（流式 token）", fs=9)
qa6 = box(80, 79.5, 16, 5.2, "save_memory\n（摘要压缩）", fs=9)
arrow(qa1, qa2, style="-")
arrow(qa2, qa3, color=ACCENT, rad=-0.15)
arrow(qa3, qa4, color=ACCENT)
arrow(qa4, qa5, color=ACCENT)
arrow(qa5, qa6, color=ACCENT)

# ---------------- 子图：db_review ----------------
cluster(34, 43, 64, 28, "db_review 子图（变更评审 / 并行预检 + HITL）", BRAND)
r1 = box(41, 65, 13, 5.4, "load\n（工具校验）", fs=9)
r2 = box(58, 65, 16, 6.4, "fetch 并行 4 路\npre_lock / pre_rows\npre_slow / pre_meta", fs=8.5)
r3 = box(75, 65, 12, 5.4, "aggregate", fs=9)
r4 = box(90, 65, 11, 5.4, "grade\n（分级）", fs=9)
r5 = box(90, 56.5, 11, 5.2, "suggest\n（建议）", fs=9)
r6 = box(75, 56.5, 12, 5.6, "approve\ninterrupt\n(change_approve)", fs=9, ec=GOLD)
r7 = box(58, 56.5, 12, 5.4, "persist\n（落库）", fs=9)
arrow(r1, r2, color=BRAND)
arrow(r2, r3, color=BRAND)
arrow(r3, r4, color=BRAND)
arrow(r4, r5, color=BRAND)
arrow(r5, r6, color=GOLD)
arrow(r6, r7, color=GOLD)
arrow(r1, r7, color=GRAY, ls=":", rad=0.35)

# ---------------- 子图：db_release ----------------
cluster(34, 13, 64, 27, "db_release 子图（沙箱验证 / HITL 放行）", "#722ed1")
d1 = box(41, 33, 14, 5.4, "load_request\n（无 SQL 入参）", fs=9)
d2 = box(58, 33, 14, 6, "guard\napproved / env=sandbox\n单语句 / 非事务", fs=8.5)
d3 = box(75, 33, 15, 5.6, "shadow_execute\nsql_exec_sandbox", fs=9)
d4 = box(90, 33, 11, 5.4, "verify\n（指标）", fs=9)
d5 = box(90, 24.5, 11, 5.6, "gate\ninterrupt\n(gate_approve)", fs=9, ec=GOLD)
d6 = box(74, 24.5, 13, 5.4, "persist\n（落库 blocked/ready）", fs=8.5)
arrow(d1, d2, color="#722ed1")
arrow(d2, d3, color="#722ed1")
arrow(d3, d4, color="#722ed1")
arrow(d4, d5, color=GOLD)
arrow(d5, d6, color=GOLD)
arrow(d2, d6, color=GRAY, ls=":", rad=0.35)

# ---------------- 父 -> 子 ----------------
arrow((26, 56), (34.5, 87), color=ACCENT, ls="--", rad=0.12)
arrow((26, 56), (34.5, 65), color=BRAND, ls="--", rad=0.05)
arrow((26, 56), (34.5, 33), color="#722ed1", ls="--", rad=-0.12)
ax.text(27.2, 89.5, "qa", fontsize=8.5, color=ACCENT, style="italic")
ax.text(27.2, 66.8, "db_review", fontsize=8.5, color=BRAND, style="italic")
ax.text(27.2, 34.6, "db_release", fontsize=8.5, color="#722ed1", style="italic")

# ---------------- 子 -> 父（结果回写） ----------------
arrow((88, 79.5), (26, 45.5), color=GRAY, ls=":", rad=-0.18)
arrow((58, 56.5), (26, 45.5), color=GRAY, ls=":", rad=-0.1)
arrow((74, 24.5), (26, 45.5), color=GRAY, ls=":", rad=0.12)

# ---------------- HITL 恢复 ----------------
box(
    50,
    5.6,
    46,
    5.4,
    "HITL 恢复：POST /unified/chat/resume → Command(resume) → 从 interrupt 继续\n"
    "（审批前段统计写入 state，最终 result_card 合并展示 耗时 / tokens）",
    fc="#fffbe6",
    ec=GOLD,
    fs=9,
)
arrow((75, 54), (73, 8.5), color=GOLD, ls="-.", rad=-0.25)
arrow((90, 22), (76, 8.5), color=GOLD, ls="-.", rad=0.25)

# ---------------- 图例 ----------------
ax.text(34.5, 99.3, "实线=串行  虚线/点线=路由或回写  金色=HITL 门禁", fontsize=9, color=GRAY)

out_dir = r"e:\cywork\python\project\agent-platform\docs\graphs"
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, "unified_agent_orchestration.png")
fig.savefig(out, bbox_inches="tight", facecolor="white")
print("SAVED", out)
print("SIZE", os.path.getsize(out))
