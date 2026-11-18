"""code_exec 工具：代码题沙箱评估，provider 可扩展（配置从 agent_tool.config 读取）。"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

import httpx

from backend.common.logger import logger
from backend.data.dao.agent.tool_dao import get_tool_config
from backend.tools.protocol import BaseTool

# provider 名称 → 执行函数（参数为 code/language/cfg）。
# 内置 http provider（对接任意兼容的沙箱 HTTP 服务）；后续接 E2B/Docker 时在此注册。
_PROVIDERS: Dict[str, Callable[..., Awaitable[dict]]] = {}


def _degraded(code: str, stderr: str) -> dict:
    return {"stdout": "", "stderr": stderr, "exit_code": -1, "degraded": True}


class CodeExecTool(BaseTool):
    """代码沙箱执行工具：未配置 provider 或执行失败返回降级结构，不抛异常。"""

    name = "code_exec"
    description = "在受控沙箱执行代码片段并返回结果/错误"

    async def run(self, **kwargs: Any) -> dict:
        code = kwargs.get("code", "")
        language = kwargs.get("language", "python")
        cfg = await get_tool_config("code_exec")
        provider = cfg.get("provider")
        handler = _PROVIDERS.get(provider) if provider else None
        if handler is None:
            return _degraded(code, f"沙箱 provider 未配置或未实现: {provider!r}")
        try:
            return await handler(code=code, language=language, cfg=cfg)
        except Exception as exc:  # noqa: BLE001 - 沙箱失败降级
            logger.warning("code_exec.failed", provider=provider, error=str(exc))
            return _degraded(code, str(exc))


async def _exec_http(*, code: str, language: str, cfg: dict) -> dict:
    """对接任意兼容的沙箱 HTTP 服务（endpoint / api_key 从 config 读取）。"""
    endpoint = cfg.get("endpoint")
    if not endpoint:
        return _degraded(code, "http provider 缺少 endpoint")
    headers = {}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    async with httpx.AsyncClient(timeout=float(cfg.get("timeout", 30))) as client:
        resp = await client.post(
            endpoint, json={"code": code, "language": language}, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
    return {
        "stdout": data.get("stdout", ""),
        "stderr": data.get("stderr", ""),
        "exit_code": int(data.get("exit_code", 0)),
    }


_PROVIDERS["http"] = _exec_http
