"""运维指标端点（/metrics）：Prometheus 文本格式、免鉴权，供监控系统抓取。

只读、低开销：仅暴露进程与组件连接态，不做真实探活（深探活请用 /health?deep=true）。
"""

from __future__ import annotations

import platform
from datetime import datetime

from fastapi import APIRouter, Response

from backend.app_state import app_state

router = APIRouter(tags=["ops"])


def _escape(value: str) -> str:
    """转义 Prometheus 标签值中的反斜杠、双引号与换行。"""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _gauge(lines: list[str], name: str, help_: str, samples: list[str]) -> None:
    """追加一个 gauge 指标（HELP / TYPE + 样本行）。"""
    lines.append(f"# HELP {name} {help_}")
    lines.append(f"# TYPE {name} gauge")
    lines.extend(samples)


@router.get("/metrics", summary="运维指标（Prometheus 文本，免鉴权）")
async def metrics() -> Response:
    """暴露进程级运维指标（Prometheus text exposition format）。

    免鉴权，供 Prometheus / 监控系统抓取。
    """
    lines: list[str] = []

    # 进程存活
    _gauge(lines, "agent_platform_up", "1=进程存活", ["agent_platform_up 1"])

    # 构建/环境信息：标签承载元数据
    svc = app_state.settings.service
    env = app_state.settings.app_env
    _gauge(
        lines,
        "agent_platform_build_info",
        "构建与环境信息（标签承载元数据）",
        [
            "agent_platform_build_info"
            f'{{version="{_escape(str(svc.version))}",env="{_escape(str(env))}",'
            f'python="{_escape(platform.python_version())}"}} 1'
        ],
    )

    # 运行时长（秒）
    started_at = app_state.started_at
    uptime = (datetime.now() - started_at).total_seconds() if started_at else 0.0
    _gauge(
        lines,
        "agent_platform_uptime_seconds",
        "进程运行时长（秒）",
        [f"agent_platform_uptime_seconds {uptime:.3f}"],
    )

    # 进程常驻内存（psutil 为可选依赖，缺失则跳过该项）
    try:
        import psutil  # type: ignore

        _gauge(
            lines,
            "process_resident_memory_bytes",
            "进程常驻内存（字节）",
            [f"process_resident_memory_bytes {psutil.Process().memory_info().rss}"],
        )
    except Exception:  # noqa: BLE001 - 指标可选，缺失不影响其它指标
        pass

    # 各组件健康（浅检查：连接态，不做真实探活）
    samples: list[str] = []
    for name in app_state.clients.names():
        client = app_state.clients.get(name)
        try:
            up = 1 if client is not None and client.is_connected else 0
        except Exception:  # noqa: BLE001
            up = 0
        samples.append(f'agent_platform_component_up{{component="{_escape(str(name))}"}} {up}')
    if samples:
        _gauge(lines, "agent_platform_component_up", "组件健康（1=up）", samples)

    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
