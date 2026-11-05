"""构造 Nacos AI release_mcp_server 所需的 SDK 强类型参数。

仅负责“发布本平台 MCP Server”的参数装配；从 Nacos 加载远程资产
（Agent Card / MCP Server）的逻辑在 ``nacos_ai_manager.py`` 中。SDK 为软依赖：
缺失时由调用方在装配阶段捕获 ImportError 并降级。
"""
from __future__ import annotations

from typing import Any


def build_mcp_release_params(nacos_ai_cfg: Any, service_cfg: Any) -> dict:
    """基于配置装配 ``release_mcp_server`` 的三个 spec 对象。

    Args:
        nacos_ai_cfg: :class:`NacosAISettings`（需含 publish_mcp 相关字段）。
        service_cfg: ServiceSettings（需含 ``ip`` / ``port``）。
    Returns:
        ``{"server_spec", "tool_spec", "mcp_endpoint_spec"}``，
        其中 ``tool_spec`` 在无可发布工具时为 ``None``。
    """
    from v2.nacos.ai.model.ai_constant import AIConstants
    from v2.nacos.ai.model.mcp.mcp import (
        McpCapability,
        McpEndpointSpec,
        McpServerBasicInfo,
        McpTool,
        McpToolSpecification,
    )
    from v2.nacos.ai.model.mcp.registry import ServerVersionDetail

    capabilities = [McpCapability(c) for c in (nacos_ai_cfg.mcp_capabilities or [])]

    # 发布版本（区别于加载远程用的 load_mcp_version）；缺省 1.0.0，避免空串被 SDK 拒
    mcp_version = nacos_ai_cfg.mcp_version or "1.0.0"
    server_spec = McpServerBasicInfo(
        name=nacos_ai_cfg.mcp_server_name,
        protocol=nacos_ai_cfg.mcp_protocol,
        frontProtocol=nacos_ai_cfg.mcp_front_protocol,
        description=nacos_ai_cfg.mcp_description,
        # version 已废弃，SDK 的 release_mcp_server 实读 versionDetail.version，
        # 不设置会导致 'NoneType' object has no attribute 'version'
        version=mcp_version,
        versionDetail=ServerVersionDetail(version=mcp_version),
        status=AIConstants.MCP_STATUS_ACTIVE,
        capabilities=capabilities or None,
        enabled=True,
    )

    tools = [
        McpTool(
            name=t.get("name"),
            description=t.get("description"),
            inputSchema=t.get("inputSchema"),
        )
        for t in (nacos_ai_cfg.mcp_tools or [])
    ]
    tool_spec = McpToolSpecification(tools=tools) if tools else None

    endpoint_spec = McpEndpointSpec(
        type=AIConstants.MCP_ENDPOINT_TYPE_DIRECT,
        data={
            "address": service_cfg.ip,
            "port": str(service_cfg.port),
            "path": nacos_ai_cfg.mcp_endpoint_path,
        },
    )

    return {
        "server_spec": server_spec,
        "tool_spec": tool_spec,
        "mcp_endpoint_spec": endpoint_spec,
    }
