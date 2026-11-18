"""一键重跑 30 条路由评测（三档）并重生成报告。

档位口径：
  1. rule       直连 classify_intent，纯关键词、无 LLM，与历史 17/30 可比；
  2. http       端到端 chat/stream，INTENT_LLM_FALLBACK=0，只验证「多 Agent 不再被截断」；
  3. http-llm   端到端 chat/stream，兜底开启（默认行为、线上真实路径）。

用法（在项目根执行）：
    python offline/rerun_route_eval.py --username <租户账号> --password <口令> --tenant-id 1
    python offline/rerun_route_eval.py --token <JWT>                 # 已有 token
    python offline/rerun_route_eval.py --skip-http                   # 只跑规则层，不用起服务
    python offline/rerun_route_eval.py ... --dry-run                 # 只打印命令不执行

前置：后端已起（默认 http://127.0.0.1:9800），账号需为租户用户（超管 tenant 0 会被 403）。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 自测包优先（含接口/请求体/标签修正），回退项目内副本
EVAL_SCRIPT_CANDIDATES = [
    Path("E:/cyfiles/简历/自测包/route_eval.py"),
    ROOT / "data" / "route_eval.py",
]
CASES_CANDIDATES = [
    Path("E:/cyfiles/简历/自测包/route_eval_cases.csv"),
    ROOT / "data" / "route_eval_cases.csv",
]
# 本项目实际运行环境（含 uuid6 / loguru / pytest）
FALLBACK_PYTHONS = [
    Path(r"D:\dev\miniconda3\envs\agent_platform\python.exe"),
]


def pick(paths: list[Path], what: str) -> Path:
    for p in paths:
        if p and p.exists():
            return p
    listing = "\n".join("  - %s" % p for p in paths)
    sys.exit("找不到%s，候选路径均不存在：\n%s" % (what, listing))


def child_env(llm_fallback: bool | None) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    if llm_fallback is None:
        env.pop("INTENT_LLM_FALLBACK", None)
    else:
        env["INTENT_LLM_FALLBACK"] = "1" if llm_fallback else "0"
    return env


def deps_ok(py: Path) -> bool:
    try:
        r = subprocess.run(
            [str(py), "-c", "import backend.services.intent_router"],
            cwd=ROOT, capture_output=True, timeout=90, env=child_env(None),
        )
        return r.returncode == 0
    except Exception:
        return False


def resolve_python(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    if deps_ok(Path(sys.executable)):
        return Path(sys.executable)
    for cand in FALLBACK_PYTHONS:
        if cand.exists() and deps_ok(cand):
            print("[info] 当前解释器缺项目依赖，改用 %s" % cand)
            return cand
    sys.exit(
        "解释器无法 import backend.services.intent_router。\n"
        "请用运行后端的那一个，例如：\n"
        r"  python offline/rerun_route_eval.py --python D:\dev\miniconda3\envs\agent_platform\python.exe"
    )


def health(base_url: str, timeout: float = 3.0) -> str:
    url = base_url.rstrip("/") + "/api/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        status = (payload.get("data") or {}).get("status") or "ok"
        return "ok:%s" % status
    except urllib.error.HTTPError as exc:
        return "http-%s" % exc.code
    except Exception as exc:  # noqa: BLE001
        return "down:%s" % type(exc).__name__


def run(cmd: list[str], env: dict, title: str, dry: bool) -> int:
    print("\n" + "-" * 72)
    print("[%s]" % title)
    print("  " + " ".join(str(c) for c in cmd))
    if dry:
        return 0
    r = subprocess.run(cmd, cwd=ROOT, env=env)
    if r.returncode != 0:
        print("[warn] 退出码 %d，后续步骤继续" % r.returncode)
    return r.returncode


def load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def brief(d: dict) -> dict:
    return {
        "hit": d.get("hit"),
        "total": d.get("total"),
        "f1": (d.get("agent_level") or {}).get("f1"),
        "clarify": d.get("clarify_fallback_rate"),
        "p95": (d.get("latency_ms") or {}).get("p95"),
    }


def multi_split(d: dict) -> tuple[int, int]:
    rows = [r for r in (d.get("results") or []) if "+" in (r.get("expect") or "")]
    return sum(1 for r in rows if r.get("hit")), len(rows)


def fmt(v, pattern: str, suffix: str = "") -> str:
    if v is None:
        return "-"
    try:
        return (pattern % v) + suffix
    except TypeError:
        return str(v)


def pad(text: str, width: int) -> str:
    """按显示宽度补齐（中文按 2 列算），保证表头与数据对齐。"""
    shown = sum(2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1 for ch in text)
    return text + " " * max(0, width - shown)


def print_table(rows: list[tuple[str, dict | None]]) -> None:
    head = ("口径", "命中", "Agent F1", "澄清回退", "多意图", "P95(ms)")
    widths = (30, 10, 11, 11, 10, 10)
    line = "".join(pad(h, w) for h, w in zip(head, widths))
    print("\n" + line)
    print("-" * sum(widths))
    for name, d in rows:
        if not d:
            print(pad(name, widths[0]) + "未产出")
            continue
        b = brief(d)
        mh, mt = multi_split(d)
        clarify = "-" if b["clarify"] is None else "%.1f%%" % (b["clarify"] * 100)
        cells = (
            "%s/%s" % (b["hit"], b["total"]),
            fmt(b["f1"], "%.4f"),
            clarify,
            "%d/%d" % (mh, mt),
            fmt(b["p95"], "%.1f"),
        )
        print(pad(name, widths[0]) + "".join(pad(c, w) for c, w in zip(cells, widths[1:])))


def load_eval_module(script: Path):
    spec = importlib.util.spec_from_file_location("route_eval_mod", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def probe_multi(base_url: str, token: str, timeout: float = 60.0) -> tuple[str, list[str]]:
    """用一条已知双意图问句探测 routing_decision 是否带出多 Agent 集合。

    补丁后应返回 agents=['db_review','db_release']；若只有 agent_type 且无 agents，
    说明后端仍跑旧代码（多半是没重启）。
    """
    url = base_url.rstrip("/") + "/api/v1/tenant/unified/chat/stream"
    body = json.dumps(
        {
            "session_id": "probe-%d" % int(time.time() * 1000),
            "message": "先看下这条 alter 的风险，没问题就帮我发到沙箱",
        },
        ensure_ascii=False,
    )
    req = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "text/event-stream",
            "Authorization": "Bearer %s" % token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if ev.get("type") == "routing_decision":
                    return str(ev.get("agent_type") or ""), list(ev.get("agents") or [])
    except urllib.error.HTTPError as exc:
        return "http-%s" % exc.code, []
    except Exception as exc:  # noqa: BLE001 - 探测失败不该阻断跑数
        return "error:%s" % type(exc).__name__, []
    return "no-event", []


def main() -> None:
    ap = argparse.ArgumentParser(description="重跑 30 条路由评测并重生成报告")
    ap.add_argument("--base-url", default="http://127.0.0.1:9800")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="123456")
    ap.add_argument("--tenant-id", default="1")
    ap.add_argument("--token", default=None, help="已有 JWT，传了就不走登录")
    ap.add_argument("--cases", default=None)
    ap.add_argument("--eval-script", default=None)
    ap.add_argument("--python", default=None, help="运行后端的那个解释器")
    ap.add_argument("--out-dir", default="data")
    ap.add_argument("--report", default="docs/路由评测报告-30条.md")
    ap.add_argument("--timeout", default="120", help="单条端到端请求超时秒数")
    ap.add_argument("--skip-rule", action="store_true")
    ap.add_argument("--skip-http", action="store_true")
    ap.add_argument("--skip-llm", action="store_true", help="跳过第三档（开兜底）")
    ap.add_argument("--skip-report", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    out_dir = ROOT / a.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    py = resolve_python(a.python)
    script = Path(a.eval_script) if a.eval_script else pick(EVAL_SCRIPT_CANDIDATES, "评测脚本")
    cases = Path(a.cases) if a.cases else pick(CASES_CANDIDATES, "标注集")

    f_rule = out_dir / "route_result.json"
    f_http = out_dir / "route_result_http.json"
    f_http_llm = out_dir / "route_result_http_llm.json"
    f_before = out_dir / "route_result_http_before.json"

    # 复跑前快照旧结果，保住「修复前」对照；已有快照则不覆盖
    if f_http.exists() and not f_before.exists():
        shutil.copy2(f_http, f_before)
        print("[info] 已快照修复前结果 -> %s" % f_before.name)
    before = load(f_before)

    print("项目根：%s" % ROOT)
    print("解释器：%s" % py)
    print("评测脚本：%s" % script)
    print("标注集：%s" % cases)

    rc: list[int] = []

    if not a.skip_rule:
        rc.append(run(
            [str(py), str(script), "--mode", "rule", "--cases", str(cases),
             "--tenant-id", str(a.tenant_id), "--out", str(f_rule)],
            child_env(None), "1/3 规则层（纯关键词，无 LLM）", a.dry_run,
        ))

    http_ok = False
    if not a.skip_http:
        state = "skip" if a.dry_run else health(a.base_url)
        print("\n[info] 服务探测 %s/api/v1/health -> %s" % (a.base_url, state))
        if state.startswith(("down", "http-")):
            print("[warn] 服务不可达，跳过端到端两档。先起后端：见 README「启动后端（默认 9800）」")
        else:
            http_ok = True
            # 补丁生效探测：多意图问句若仍只回单 Agent，说明后端跑的还是旧代码
            if not a.dry_run:
                try:
                    mod = load_eval_module(script)
                    tk = a.token or mod.http_login(
                        a.base_url, a.username, a.password, int(a.tenant_id), 30
                    )
                    at, agents = probe_multi(a.base_url, tk)
                    if len(agents) >= 2:
                        print("[info] 补丁生效：多意图问句 routing_decision agents=%s" % agents)
                    elif at == "http-403":
                        print(
                            "[warn] 当前账号无租户上下文（403），端到端两档会全部 403。\n"
                            "       换租户账号，或用 --token 传入租户用户的 JWT。"
                        )
                    elif at.startswith(("http-", "error:", "no-event")):
                        print("[warn] 补丁生效探测未取得结果（%s），跑完以实际命中数为准" % at)
                    else:
                        print(
                            "[warn] 补丁疑似未生效：多意图问句只回 agent_type=%s agents=%s。\n"
                            "       后端多半没重启，请重启服务后再跑，否则端到端仍是旧行为。"
                            % (at, agents)
                        )
                except Exception as exc:  # noqa: BLE001 - 探测失败不影响后续跑数
                    print("[warn] 补丁生效探测失败（不影响后续跑数）：%s" % exc)
            common = [str(py), str(script), "--mode", "http", "--base-url", a.base_url,
                      "--cases", str(cases), "--timeout", str(a.timeout)]
            auth = (["--token", a.token] if a.token
                    else ["--username", a.username, "--password", a.password,
                          "--tenant-id", str(a.tenant_id)])
            rc.append(run(
                common + auth + ["--out", str(f_http)],
                child_env(False), "2/3 端到端（关兜底，验证多 Agent 修复）", a.dry_run,
            ))
            if not a.skip_llm:
                rc.append(run(
                    common + auth + ["--out", str(f_http_llm)],
                    child_env(True), "3/3 端到端（开兜底，线上真实路径）", a.dry_run,
                ))

    if not a.skip_report and not a.dry_run:
        run(
            [str(py), str(ROOT / "offline" / "route_eval_report.py"), "--out", a.report],
            child_env(None), "重生成评测报告", a.dry_run,
        )

    if a.dry_run:
        print("\n[dry-run] 以上命令未执行")
        return

    print("\n" + "=" * 72)
    print("三档对照")
    did_llm = http_ok and not a.skip_llm
    print_table([
        ("修复前（快照）", before),
        ("修复后·关兜底" + ("" if http_ok else "（本次未跑）"), load(f_http)),
        ("修复后·开兜底" + ("" if did_llm else "（本次未跑）"), load(f_http_llm)),
        ("规则层（参照）" + ("" if not a.skip_rule else "（本次未跑）"), load(f_rule)),
    ])

    print("\n产物：")
    for p in (f_rule, f_http, f_http_llm, ROOT / a.report):
        print("  %-46s %s" % (p.relative_to(ROOT) if p.is_relative_to(ROOT) else p,
                              "存在" if p.exists() else "缺失"))
    if any(rc):
        print("\n有步骤返回非 0，检查上方日志（常见：账号非租户用户 403 / 服务未起）")
    print("\n下一步：把上表的命中数、Agent F1、多意图分层发我，改成简历句并配追问防御。")


if __name__ == "__main__":
    main()
