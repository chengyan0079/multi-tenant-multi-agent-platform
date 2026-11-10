"""Nacos AI 客户端封装（SDK NacosAIService）：MCP Server/Agent Card/Prompt/Skill；需 >=3.1.0，SDK 缺失软降级。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.common.logger import logger
from backend.common.nacos_compat import import_error_hint, normalize_namespace_id
from backend.data.clients.base import BaseClient, ClientError

try:  # SDK 软依赖：缺失时模块仍可加载，调用能力方法时由 raw 守卫抛错
    from v2.nacos.ai.nacos_ai_service import NacosAIService
    from v2.nacos.ai.model.ai_param import (
        DeregisterAgentEndpointParam,
        DownloadSkillParam,
        GetAgentCardParam,
        GetMcpServerParam,
        GetPromptParam,
        RegisterAgentEndpointParam,
        RegisterMcpServerEndpointParam,
        ReleaseAgentCardParam,
        ReleaseMcpServerParam,
        SubscribeAgentCardParam,
        SubscribeMcpServerParam,
        SubscribePromptParam,
    )

    # 修 v2.nacos 在 pydantic v2 下序列化崩溃：GrpcUtils.to_json 未用 mode='json'，嵌套 Enum 落入 __dict__ 递归报错，故打补丁。
    from enum import Enum
    from v2.nacos.transport.grpc_util import GrpcUtils

    def _patch_nacos_grpc_to_json() -> None:
        def _to_json(obj):
            if hasattr(obj, "model_dump"):
                try:
                    return obj.model_dump(by_alias=True, exclude_none=True, mode="json")
                except Exception:
                    pass
            if isinstance(obj, Enum):
                return obj.value
            if hasattr(obj, "__dict__"):
                return vars(obj)
            return str(obj)

        GrpcUtils.to_json = staticmethod(_to_json)

    _patch_nacos_grpc_to_json()
except ImportError:  # pragma: no cover - SDK 缺失分支
    NacosAIService = None  # type: ignore[assignment]
    DeregisterAgentEndpointParam = None  # type: ignore[assignment]
    DownloadSkillParam = None  # type: ignore[assignment]
    GetAgentCardParam = None  # type: ignore[assignment]
    GetMcpServerParam = None  # type: ignore[assignment]
    GetPromptParam = None  # type: ignore[assignment]
    RegisterAgentEndpointParam = None  # type: ignore[assignment]
    RegisterMcpServerEndpointParam = None  # type: ignore[assignment]
    ReleaseAgentCardParam = None  # type: ignore[assignment]
    ReleaseMcpServerParam = None  # type: ignore[assignment]
    SubscribeAgentCardParam = None  # type: ignore[assignment]
    SubscribeMcpServerParam = None  # type: ignore[assignment]
    SubscribePromptParam = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from v2.nacos import NacosAIService as _AIService


def _guard_param(cls: Any) -> Any:
    if cls is None:
        raise ClientError("nacos-sdk-python 未安装，无法使用 Nacos AI")
    return cls


class NacosAIClient(BaseClient):
    """Nacos AI（MCP Server / Agent Card / Prompt / Skill）。"""

    name = "nacos_ai"

    def __init__(
        self,
        server_addr: str,
        namespace: str,
        group: str = "DEFAULT_GROUP",
        user: str = "",
        password: str = "",
        access_key: str = "",
        secret_key: str = "",
    ) -> None:
        self._server_addr = server_addr
        self._namespace = normalize_namespace_id(namespace)
        self._group = group or "DEFAULT_GROUP"
        self._user = user or ""
        self._password = password or ""
        self._access_key = access_key or ""
        self._secret_key = secret_key or ""
        self._raw: "_AIService | None" = None

    @classmethod
    def from_settings(cls, cfg: Any) -> "NacosAIClient":
        return cls(
            server_addr=cfg.server_addr,
            namespace=cfg.namespace,
            group=getattr(cfg, "group", "DEFAULT_GROUP") or "DEFAULT_GROUP",
            user=getattr(cfg, "user", "") or "",
            password=getattr(cfg, "password", "") or "",
            access_key=getattr(cfg, "access_key", "") or "",
            secret_key=getattr(cfg, "secret_key", "") or "",
        )

    # ---------- 生命周期 ----------
    @property
    def is_connected(self) -> bool:
        return self._raw is not None

    async def connect(self) -> None:
        if self._raw is not None:
            return
        if NacosAIService is None:
            logger.warning(import_error_hint("Nacos AI"))
            return
        from v2.nacos import ClientConfig

        cc = ClientConfig(
            server_addresses=self._server_addr,
            namespace_id=self._namespace,
            username=self._user or None,
            password=self._password or None,
            access_key=self._access_key or None,
            secret_key=self._secret_key or None,
        )
        self._raw = await NacosAIService.create_ai_service(cc)

    async def close(self) -> None:
        if self._raw is None:
            return
        try:
            await self._raw.shutdown()
        except Exception:  # noqa: BLE001
            pass
        self._raw = None

    @property
    def raw(self) -> "_AIService":
        if self._raw is None:
            raise ClientError("Nacos AI 未连接")
        return self._raw

    async def health_check(self) -> bool:
        # AIService 未暴露 server_health，以连接态为准
        return self.is_connected

    # ---------- MCP Server ----------
    async def get_mcp_server(self, mcp_name: str, version: str | None = None):
        return await self.raw.get_mcp_server(
            _guard_param(GetMcpServerParam)(mcp_name=mcp_name, version=version)
        )

    async def release_mcp_server(
        self,
        server_spec: Any,
        tool_spec: Any = None,
        mcp_endpoint_spec: Any = None,
    ):
        return await self.raw.release_mcp_server(
            _guard_param(ReleaseMcpServerParam)(
                server_spec=server_spec,
                tool_spec=tool_spec,
                mcp_endpoint_spec=mcp_endpoint_spec,
            )
        )

    async def register_mcp_server_endpoint(
        self, mcp_name: str, address: str, port: int, version: str | None = None
    ):
        return await self.raw.register_mcp_server_endpoint(
            _guard_param(RegisterMcpServerEndpointParam)(
                mcp_name=mcp_name, address=address, port=port, version=version
            )
        )

    async def subscribe_mcp_server(
        self, mcp_name: str, version: str | None, subscribe_callback: Any
    ):
        return await self.raw.subscribe_mcp_server(
            _guard_param(SubscribeMcpServerParam)(
                mcp_name=mcp_name, version=version, subscribe_callback=subscribe_callback
            )
        )

    async def unsubscribe_mcp_server(
        self, mcp_name: str, version: str | None, subscribe_callback: Any
    ) -> None:
        await self.raw.unsubscribe_mcp_server(
            _guard_param(SubscribeMcpServerParam)(
                mcp_name=mcp_name, version=version, subscribe_callback=subscribe_callback
            )
        )

    # ---------- Agent Card ----------
    async def get_agent_card(
        self, agent_name: str, version: str | None = None, registration_type: str | None = None
    ):
        return await self.raw.get_agent_card(
            _guard_param(GetAgentCardParam)(
                agent_name=agent_name, version=version, registration_type=registration_type
            )
        )

    async def release_agent_card(
        self, agent_card: Any, registration_type: str = "service", set_as_latest: bool = False
    ):
        return await self.raw.release_agent_card(
            _guard_param(ReleaseAgentCardParam)(
                agent_card=agent_card,
                registration_type=registration_type,
                set_as_latest=set_as_latest,
            )
        )

    async def register_agent_endpoint(
        self,
        agent_name: str,
        address: str,
        port: int,
        version: str,
        transport: str = "JSONRPC",
        path: str = "/agent",
        support_tls: bool = False,
    ):
        return await self.raw.register_agent_endpoint(
            _guard_param(RegisterAgentEndpointParam)(
                agent_name=agent_name,
                address=address,
                port=port,
                version=version,
                transport=transport,
                path=path,
                support_tls=support_tls,
            )
        )

    async def deregister_agent_endpoint(
        self, agent_name: str, address: str, port: int, version: str
    ):
        return await self.raw.deregister_agent_endpoint(
            _guard_param(DeregisterAgentEndpointParam)(
                agent_name=agent_name, address=address, port=port, version=version
            )
        )

    async def subscribe_agent_card(
        self, agent_name: str, version: str | None, subscribe_callback: Any
    ):
        return await self.raw.subscribe_agent_card(
            _guard_param(SubscribeAgentCardParam)(
                agent_name=agent_name, version=version, subscribe_callback=subscribe_callback
            )
        )

    async def unsubscribe_agent_card(
        self, agent_name: str, version: str | None, subscribe_callback: Any
    ) -> None:
        await self.raw.unsubscribe_agent_card(
            _guard_param(SubscribeAgentCardParam)(
                agent_name=agent_name, version=version, subscribe_callback=subscribe_callback
            )
        )

    # ---------- Prompt ----------
    async def get_prompt(
        self, prompt_key: str, version: str | None = None, label: str | None = None
    ):
        return await self.raw.get_prompt(
            _guard_param(GetPromptParam)(prompt_key=prompt_key, version=version, label=label)
        )

    async def subscribe_prompt(
        self,
        prompt_key: str,
        version: str | None,
        subscribe_callback: Any,
        label: str | None = None,
    ):
        return await self.raw.subscribe_prompt(
            _guard_param(SubscribePromptParam)(
                prompt_key=prompt_key,
                version=version,
                subscribe_callback=subscribe_callback,
                label=label,
            )
        )

    async def unsubscribe_prompt(
        self,
        prompt_key: str,
        version: str | None,
        subscribe_callback: Any,
        label: str | None = None,
    ) -> None:
        await self.raw.unsubscribe_prompt(
            _guard_param(SubscribePromptParam)(
                prompt_key=prompt_key,
                version=version,
                subscribe_callback=subscribe_callback,
                label=label,
            )
        )

    # ---------- Skill ----------
    async def download_skill_zip(
        self, skill_name: str, version: str | None = None, label: str | None = None
    ):
        return await self.raw.download_skill_zip(
            _guard_param(DownloadSkillParam)(skill_name=skill_name, version=version, label=label)
        )
