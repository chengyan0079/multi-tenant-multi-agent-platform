"""路由评测复核与诊断报告：读取 route_eval.py 的两份结果 json，重新计算并定位差异来源。

用法：
    python offline/route_eval_report.py \
        --rule data/route_result.json \
        --http data/route_result_http.json \
        --out docs/路由评测报告-30条.md

设计约束：
* 关键词表**从源码用 ast 解析**，不复制、不硬编码，避免与 backend 实现漂移。
* 不依赖 backend 运行时（无需数据库、无需 LLM），可在任意 Python 环境复现。
* 所有数字均为「分母显式」口径，不输出孤立百分比。
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTENT_SRC = ROOT / "backend" / "services" / "intent_router.py"
ROUTER_SRC = ROOT / "backend" / "orchestration" / "unified_intent.py"
DEPS_SRC = ROOT / "backend" / "api" / "v1" / "tenant" / "agent" / "unified_deps.py"


def src(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def fix_status() -> dict[str, bool]:
    """按源码实际内容判定 D1~D6 是否已修（不靠注释、不靠人记）。"""
    it, rt, dp = src(INTENT_SRC), src(ROUTER_SRC), src(DEPS_SRC)
    return {
        "D1": 'label="multi_agent"' in it and "plan_from_decision" in it,
        "D2": "_llm_fallback_enabled" in it and "classify_as_intent" in dp,
        "D3": "from backend.common.llm.llm_factory import get_structured_llm" in rt,
        "D4": "await _llm_agents(" in it,
        "D5": "exc_info=True" in rt,
        "D6": '["db_review", "db_release"] +' not in it,
    }


def load_keywords() -> dict[str, tuple[str, ...]]:
    """从 intent_router.py 解析 _KEYWORDS（不 import，避免拉起依赖）。"""
    tree = ast.parse(INTENT_SRC.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "_KEYWORDS":
            return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "_KEYWORDS" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise SystemExit("未在 intent_router.py 中找到 _KEYWORDS")


def rule_agents(text: str, table: dict[str, tuple[str, ...]]) -> list[str]:
    low = (text or "").lower()
    return [a for a, kws in table.items() if any(k.lower() in low for k in kws)]


def as_label(agents: list[str]) -> str:
    """评测脚本口径：空集 → clarify，多 Agent 按字母序用 + 连接。"""
    return "+".join(sorted(set(agents))) if agents else "clarify"


def classify_kind(expect: str) -> str:
    if expect == "clarify":
        return "clarify（澄清/越界负例）"
    return "multi（多意图组合）" if "+" in expect else "single（单意图）"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", default="data/route_result.json")
    ap.add_argument("--http", default="data/route_result_http.json")
    ap.add_argument(
        "--http-before",
        default="data/route_result_http_before.json",
        help="修复前的端到端结果，用于前后对照；文件不存在则跳过该节",
    )
    ap.add_argument(
        "--http-llm",
        default="data/route_result_http_llm.json",
        help="修复后且开启 LLM 兜底（INTENT_LLM_FALLBACK=1）的端到端结果；不存在则跳过该行",
    )
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    table = load_keywords()
    rule = json.loads((ROOT / a.rule).read_text(encoding="utf-8"))
    http = json.loads((ROOT / a.http).read_text(encoding="utf-8"))
    before = None
    pb = ROOT / a.http_before
    if a.http_before and pb.exists():
        before = json.loads(pb.read_text(encoding="utf-8"))
    http_llm = None
    pl = ROOT / a.http_llm
    if a.http_llm and pl.exists():
        http_llm = json.loads(pl.read_text(encoding="utf-8"))
    fixed = fix_status()
    R = {r["id"]: r for r in rule["results"]}
    H = {r["id"]: r for r in http["results"]}
    B = {r["id"]: r for r in before["results"]} if before else {}
    ids = sorted(R)

    # ---- 复核 1：按源码关键词表重算规则层，验证与 json 一致
    recalc = {}
    for i in ids:
        recalc[i] = as_label(rule_agents(R[i]["question"], table))
    mism = [i for i in ids if recalc[i] != R[i]["pred"]]

    # ---- 复核 2：端到端结果是否等于「规则命中的第一个 Agent」
    trunc = {}
    for i in ids:
        agents = rule_agents(R[i]["question"], table)
        trunc[i] = agents[0] if agents else "clarify"
    trunc_same = [i for i in ids if trunc[i] == H[i]["pred"]]

    # ---- 复核 3：两级命中集合的包含关系
    hit_rule = {i for i in ids if R[i]["hit"]}
    hit_http = {i for i in ids if H[i]["hit"]}

    # ---- 分类统计
    kinds = ["clarify（澄清/越界负例）", "single（单意图）", "multi（多意图组合）"]
    stat: dict[str, dict[str, int]] = {k: {"n": 0, "rule": 0, "http": 0} for k in kinds}
    for i in ids:
        k = classify_kind(R[i]["expect"])
        stat[k]["n"] += 1
        stat[k]["rule"] += int(R[i]["hit"])
        stat[k]["http"] += int(H[i]["hit"])

    # ---- 关键词覆盖率分层
    layer = {"命中关键词": {"n": 0, "rule": 0, "http": 0}, "未命中关键词": {"n": 0, "rule": 0, "http": 0}}
    for i in ids:
        has = bool(rule_agents(R[i]["question"], table))
        key = "命中关键词" if has else "未命中关键词"
        layer[key]["n"] += 1
        layer[key]["rule"] += int(R[i]["hit"])
        layer[key]["http"] += int(H[i]["hit"])

    lines: list[str] = []
    w = lines.append
    _sec = [0]

    def h(title: str) -> None:
        """章节号按实际输出递增，避免「有条件插入的章节」导致编号断档。"""
        _sec[0] += 1
        w(f"## {_sec[0]}. {title}\n")

    w("# 路由评测报告（30 条标注问句）\n")
    w("> 由 `offline/route_eval_report.py` 生成。数据源：`data/route_result.json`（规则层）、"
      "`data/route_result_http.json`（端到端 SSE），修复前结果见 "
      "`data/route_result_http_before.json`。关键词表与缺陷修复状态均从源码解析，不复制、不硬编码。\n")

    h("总体结果")
    if before is not None and all(H[i]["pred"] == B[i]["pred"] for i in ids if i in B):
        w("> 注意：端到端结果与 `route_result_http_before.json` 逐条一致，说明结果文件尚未在修补后重跑。"
          "重跑 `python route_eval.py --mode http ...` 覆盖 `data/route_result_http.json` 后，本表即为修复后口径。\n")
    w("| 口径 | 命中 | 准确率 | Agent 级 P/R/F1 | 澄清回退率 | 决策耗时 mean / p95 |")
    w("|---|---|---|---|---|---|")
    for tag, d in (("规则层 `classify_intent`", rule), ("端到端 `chat/stream`", http)):
        al = d["agent_level"]
        w(f"| {tag} | {d['hit']}/{d['total']} | {d['accuracy']:.4f} | "
          f"{al['precision']:.4f} / {al['recall']:.4f} / {al['f1']:.4f} | "
          f"{d['clarify_fallback_rate']:.4f} | {d['latency_ms']['mean']:.1f} / {d['latency_ms']['p95']:.1f} ms |")
    w("")

    loss = sorted(hit_rule - hit_http)
    gain = sorted(hit_http - hit_rule)
    trunc_feature = len(trunc_same) == len(ids) and bool(loss)

    h("复核结论")
    w(f"- 按源码关键词表重算规则层：**{len(ids) - len(mism)}/{len(ids)}** 与 `route_result.json` 一致"
      + ("（无不一致）" if not mism else f"，不一致：{mism}"))
    w(f"- 端到端结果 vs 「规则命中集合的第一个 Agent」：**{len(trunc_same)}/{len(ids)}** 完全相同"
      + ("　→ 截断特征成立" if trunc_feature else "　→ 截断特征不成立"))
    w(f"- 命中集合包含关系：端到端命中 {len(hit_http)} 条，其中属于规则层命中的 "
      f"**{len(hit_http & hit_rule)}** 条；端到端比规则层多命中的 **{len(gain)}** 条")
    w(f"- 规则层命中而在端到端丢失：**{len(loss)}** 条 → {', '.join(loss) if loss else '无'}")
    w("")

    if before is not None:
        h("修复前后对照（同一标注集、同一端点）")
        w("| 口径 | 命中 | Agent 级 F1 | 说明 |")
        w("|---|---|---|---|")
        w(f"| 修复前 `chat/stream` | {before['hit']}/{before['total']} | "
          f"{before['agent_level']['f1']:.4f} | 组合意图被截断为第一个 Agent |")
        w(f"| 修复后 `chat/stream` | {http['hit']}/{http['total']} | "
          f"{http['agent_level']['f1']:.4f} | `multi_agent` + 编排 DSL 真实执行 |")
        if http_llm is not None:
            w(f"| 修复后 + LLM 兜底 | {http_llm['hit']}/{http_llm['total']} | "
              f"{http_llm['agent_level']['f1']:.4f} | 规则未命中时问一次 LLM（`INTENT_LLM_FALLBACK=1`） |")
        w(f"| 规则层（参照） | {rule['hit']}/{rule['total']} | "
          f"{rule['agent_level']['f1']:.4f} | 纯关键词，无 LLM |")
        w("")
        w(f"端到端净增 **{http['hit'] - before['hit']:+d}** 条；与规则层差额 "
          f"**{http['hit'] - rule['hit']:+d}** 条（为 0 即多 Agent 通道已与规则内核对齐）。")
        w("")

    h("分类别结果")
    w("| 类别 | 条数 | 规则层 | 端到端 |")
    w("|---|---|---|---|")
    for k in kinds:
        s = stat[k]
        w(f"| {k} | {s['n']} | {s['rule']}/{s['n']} | {s['http']}/{s['n']} |")
    w(f"| **合计** | **{len(ids)}** | **{rule['hit']}/{len(ids)}** | **{http['hit']}/{len(ids)}** |")
    w("")

    h("关键词覆盖率分层")
    w("| 分层 | 条数 | 规则层 | 端到端 |")
    w("|---|---|---|---|")
    for k, s in layer.items():
        w(f"| {k} | {s['n']} | {s['rule']}/{s['n']} | {s['http']}/{s['n']} |")
    w("")

    h("错判清单（规则层）")
    w("| ID | 问题 | 期望 | 规则层 | 端到端 | 命中的关键词 |")
    w("|---|---|---|---|---|---|")
    for i in ids:
        if R[i]["hit"]:
            continue
        kws = [k for a, ks in table.items() for k in ks if k.lower() in R[i]["question"].lower()]
        w(f"| {i} | {R[i]['question']} | `{R[i]['expect']}` | `{R[i]['pred']}` | `{H[i]['pred']}` | "
          f"{'、'.join(kws) if kws else '**无**'} |")
    w("")

    h("结论")
    w(f"1. **路由内核** `classify_intent` 命中 {rule['hit']}/{len(ids)}：澄清类 "
      f"{stat[kinds[0]]['rule']}/{stat[kinds[0]]['n']}、多意图组合 "
      f"{stat[kinds[2]]['rule']}/{stat[kinds[2]]['n']}、单意图 "
      f"{stat[kinds[1]]['rule']}/{stat[kinds[1]]['n']}。")
    miss_n = sum(1 for i in ids if not R[i]["hit"])
    miss_nokw = sum(1 for i in ids if not R[i]["hit"] and not rule_agents(R[i]["question"], table))
    w(f"2. {miss_n} 条错判中有 {miss_nokw} 条是完全不含任何关键词的长尾请求"
      "（如「评估下影响」「回滚方案写到什么粒度」），说明瓶颈在种子关键词表的覆盖，"
      f"而非串行/并行流程判定——后者在多意图类上 {stat[kinds[2]]['rule']}/{stat[kinds[2]]['n']} 成立。")
    if trunc_feature:
        w(f"3. **端到端差额集中在多意图类**：{len(loss)} 条（{', '.join(loss)}）在端到端丢失，"
          "逐条比对等于规则集合的第一个 Agent，属多 Agent 通道被截断（D1），不是分类错误。")
    else:
        w(f"3. **端到端与规则层已对齐**：多意图类端到端 {stat[kinds[2]]['http']}/{stat[kinds[2]]['n']}，"
          f"两口径总命中差额 {http['hit'] - rule['hit']:+d} 条；剩余错判两口径同源，均来自关键词覆盖。")
    w(f"4. **澄清类**规则层 {stat[kinds[0]]['rule']}/{stat[kinds[0]]['n']}、端到端 "
      f"{stat[kinds[0]]['http']}/{stat[kinds[0]]['n']}：模糊与越界请求不会被打到错误方向，"
      "这是该类系统最先要守住的一条。")
    w("")

    h("缺陷与修复状态（按源码判定）")
    w("| 编号 | 位置 | 现象 | 修复方式 | 状态 |")
    w("|---|---|---|---|---|")
    defects = [
        (
            "D1",
            "`intent_router.py` `classify_as_intent`",
            "`label=agents[0]` 把多 Agent 集合截断为第一个元素，组合诉求被静默丢弃",
            "多 Agent 返回保留标签 `multi_agent` + 编排 DSL，由 pipeline 模式真实执行",
        ),
        (
            "D2",
            "`unified_deps.py:24`",
            "注入纯规则桥接，`_default_classify` 在该路径不可达",
            "桥接层内建 LLM 兜底（`INTENT_LLM_FALLBACK` 开关），生产路径不再只有规则",
        ),
        (
            "D3",
            "`unified_intent.py` `_default_classify`",
            "`from backend.llm.llm_factory` 指向不存在的模块，一启用即 ImportError",
            "改指向 `backend.common.llm.llm_factory`",
        ),
        (
            "D4",
            "`intent_router.py` `_llm_agents`",
            "仅有定义、无调用点，与「规则无命中再交 LLM」的设计不符",
            "接入 `classify_as_intent` 的兜底分支，失败仅告警、降级 clarify",
        ),
        (
            "D5",
            "`unified_intent.py` `UnifiedRouter.route`",
            "`except Exception` 静默回退默认 Agent，故障不可观测",
            "记 `warning` 并带 `exc_info`，保留回退行为",
        ),
        (
            "D6",
            "`intent_router.py` `decide_flow`",
            "串行顺序硬编码 `db_review/db_release`，新增组合会带上不属于自己的前置步骤",
            "顺序改为取命中集合的声明次序",
        ),
    ]
    for code, loc, symptom, fix in defects:
        status = "未修复" if not fixed[code] else ("已覆盖" if code == "D2" else "已修复")
        w(f"| {code} | {loc} | {symptom} | {fix} | {status} |")
    w("")
    llm_ready = fixed["D3"] and fixed["D4"]
    w("> " + (
        "LLM 兜底通道已接线：规则未命中时调用 `_llm_agents`（`INTENT_LLM_FALLBACK=0` 可关闭），"
        "异常只告警不阻断。离线 `--mode rule` 仍走纯规则 `classify_intent`，两口径可分别报数。"
        if llm_ready
        else "LLM 兜底通道尚未接线，「规则前置 + LLM 兜底」只实现前半句。"
    ) + "\n")

    text = "\n".join(lines)
    if a.out:
        p = ROOT / a.out
        p.parent.mkdir(parents=True, exist_ok=True)
        # 显式 LF：docs/ 下既有文件均为 LF，避免混用
        with p.open("w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"已写入 {p}（{len(text)} 字符）")
    else:
        print(text)


if __name__ == "__main__":
    main()
