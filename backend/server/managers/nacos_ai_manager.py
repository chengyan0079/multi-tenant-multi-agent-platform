"""NacosAIManager：Nacos AI 接入（发布 + 加载远程资产）。

两段职责：
1. 发布本平台 MCP Server 到 Nacos AI（release_mcp_server）。
2. 从 Nacos AI 加载远程资产（Agent Card / MCP Server），按 allow-list 名称清单，
   默认走 subscribe_* 长连接实时更新（subscribe_remote=False 时退化为启动期 get_* 快照）。
   加载结果缓存在 manager 实例上，经 ``app_state.nacos_ai`` 供查询接口 / 健康检查读取；
   消费侧（如接进 plugin_registry 成可调用工具）后续单独做。

需 Nacos 服务端 >= 3.1.0，SDK（v2.nacos）缺失时软降级，不阻断启动。
生命周期与 NacosDiscoverManager 对齐：默认失败仅告警、不阻断启动（strict=True 时 fail-fast）。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from backend.app_state import app_state
from backend.common.logger import logger
from backend.config import config
from backend.data.clients.nacos import NacosAIClient
from backend.server.base_manager import BaseManager, HealthInfo
from backend.server.managers.nacos_ai_spec import build_mcp_release_params


def _is_already_exists(exc: Exception) -> bool:
    """判断 Nacos 报错是否为『MCP Server 已存在』（409 already exist）。"""
    code = getattr(exc, "error_code", None)
    if code in (409, "409"):
        return True
    msg = str(exc).lower()
    return "already exist" in msg or "do not do release" in msg


class NacosAIManager(BaseManager):
    """Nacos AI 启动项：发布本平台 MCP Server + 加载远程 Agent Card / MCP Server。"""

    def __init__(self) -> None:
        super().__init__()
        self._client: Optional[NacosAIClient] = None
        self._released_id: Optional[str] = None
        self._mcp_name: Optional[str] = None
        # 从 Nacos AI 加载到的远程资产（按名缓存），供外部查询
        self._agent_cards: Dict[str, Any] = {}
        self._mcp_servers: Dict[str, Any] = {}
        # 订阅句柄，stop 时逐一反订阅；每条记录含回调引用以便精确反订阅
        self._subscriptions: List[Dict[str, Any]] = []

    # -------------------------------------------------------------------------
    # 生命周期
    # -------------------------------------------------------------------------
    async def start(self) -> None:
        if not config.nacos_ai.enabled:
            logger.info("Nacos AI 未启用（NACOS_AI_ENABLED=False），跳过")
            return
        app_state.nacos_ai = self
        client = app_state.clients.ensure(
            "nacos_ai", lambda: NacosAIClient.from_settings(config.nacos_ai)
        )
        await client.connect()
        self._client = client
        # SDK 缺失或未连接时 is_connected 为 False（connect 内已告警），跳过后续
        if not client.is_connected:
            return

        # 加载远程资产与发布相互独立：即使不发布本平台 MCP Server，也照常加载
        await self._load_remote_assets(client)

        if not config.nacos_ai.publish_mcp:
            logger.info("Nacos AI MCP 发布未启用（publish_mcp=False），仅建立连接并加载远程资产")
            return
        try:
            params = build_mcp_release_params(config.nacos_ai, config.service)
        except Exception as e:  # 参数装配失败不应阻断启动
            if config.nacos_ai.strict:
                raise
            logger.warning(f"构造 Nacos AI MCP 发布参数失败，跳过发布: {e}")
            return
        try:
            mcp_id = await self._release_mcp_server(client, params)
            self._released_id = mcp_id
            self._mcp_name = config.nacos_ai.mcp_server_name
            logger.info(
                f"Nacos AI 发布 MCP Server 成功: {self._mcp_name} (id={mcp_id})"
            )
        except Exception as e:
            if config.nacos_ai.strict:
                raise
            logger.warning(
                f"Nacos AI 发布 MCP Server 失败（{e}），跳过发布：服务继续启动"
            )

    async def _release_mcp_server(self, client: NacosAIClient, params: Dict[str, Any]) -> str:
        """幂等发布本平台 MCP Server：已存在同名同版本则跳过重复创建。

        Nacos 的 ``release_mcp_server`` 是『创建新版本』语义，同名同版本重复发布会
        返回 409 already exist。故先 get 查询，命中即复用；未命中再创建，创建时若仍
        409（并发/查询竞态）则视为已存在，不致命。
        """
        name = config.nacos_ai.mcp_server_name
        version = config.nacos_ai.mcp_version or "1.0.0"
        # 先查：已存在则直接复用，避免 release 重复创建 409
        try:
            existing = await client.get_mcp_server(name, version)
            if existing is not None:
                logger.info(f"Nacos AI MCP Server 已存在 {name}@{version}，跳过重复发布")
                return getattr(existing, "id", None) or name
        except Exception as e:
            logger.debug(f"查询 MCP Server 失败，回落直接发布: {e}")
        # 查询未命中则创建；若仍 409（已存在）视为成功，不致命
        try:
            return await client.release_mcp_server(
                server_spec=params["server_spec"],
                tool_spec=params.get("tool_spec"),
                mcp_endpoint_spec=params["mcp_endpoint_spec"],
            )
        except Exception as e:
            if _is_already_exists(e):
                logger.info(f"Nacos AI MCP Server 已存在 {name}@{version}（release 409），跳过")
                return name
            raise

    async def stop(self) -> None:
        # 先反订阅所有远程资产订阅，断开长连接
        for sub in self._subscriptions:
            try:
                if sub["kind"] == "mcp":
                    await self._client.unsubscribe_mcp_server(
                        sub["name"], sub["version"], sub["cb"]
                    )
                else:
                    await self._client.unsubscribe_agent_card(
                        sub["name"], sub["version"], sub["cb"]
                    )
            except Exception as e:  # 反订阅失败仅告警，不阻断关停
                logger.warning(f"Nacos AI 反订阅失败: {sub['name']} ({e})")
        self._subscriptions.clear()
        self._agent_cards.clear()
        self._mcp_servers.clear()

        self._released_id = None
        self._mcp_name = None
        app_state.nacos_ai = None
        # release_mcp_server 为『创建新版本』语义，同名同版本重复会 409；
        # 启动期已改为幂等（先 get 后 release）跳过已存在，重启不再因重复发布失败。
        # 当前 SDK 未提供 MCP Server 反发布接口，此处仅释放客户端连接。
        if self._client is not None:
            await self._client.close()
        self._client = None

    async def health(self) -> HealthInfo:
        if not config.nacos_ai.enabled:
            return HealthInfo(status="running", detail="Nacos AI 未启用，跳过")
        if self._client is None or not self._client.is_connected:
            return HealthInfo(status="degraded", detail="Nacos AI 客户端未连接")
        if self._released_id or self._agent_cards or self._mcp_servers:
            detail = (
                f"已连接；发布MCP={bool(self._released_id)} "
                f"agent_cards={len(self._agent_cards)} mcp_servers={len(self._mcp_servers)}"
            )
            return HealthInfo(status="running", detail=detail)
        return HealthInfo(status="degraded", detail="已连接但未发布也未加载任何资产")

    # -------------------------------------------------------------------------
    # 远程资产加载
    # -------------------------------------------------------------------------
    async def _load_remote_assets(self, client: NacosAIClient) -> None:
        """按配置 allow-list 加载并（可选）订阅远程 Agent Card / MCP Server。

        单个资产加载失败不影响其余，默认告警跳过；strict=True 时首个失败即 fail-fast。
        """
        cfg = config.nacos_ai
        if not (cfg.load_agent_cards or cfg.load_mcp_servers):
            logger.info("Nacos AI 未配置 load_agent_cards / load_mcp_servers，跳过远程资产加载")
            return

        for name in cfg.load_agent_cards or []:
            try:
                await self._load_agent_card(client, name)
            except Exception as e:
                if cfg.strict:
                    raise
                logger.warning(f"Nacos AI 加载 Agent Card 失败: {name} ({e})，跳过")

        for name in cfg.load_mcp_servers or []:
            try:
                await self._load_mcp_server(client, name)
            except Exception as e:
                if cfg.strict:
                    raise
                logger.warning(f"Nacos AI 加载 MCP Server 失败: {name} ({e})，跳过")

        if self._agent_cards or self._mcp_servers:
            logger.info(
                f"Nacos AI 远程资产加载完成: "
                f"agent_cards={list(self._agent_cards)} mcp_servers={list(self._mcp_servers)}"
            )

    async def _load_agent_card(self, client: NacosAIClient, name: str) -> None:
        """加载（订阅或一次性拉取）单个 Agent Card 并缓存。"""
        cfg = config.nacos_ai
        version = cfg.agent_card_version
        if cfg.subscribe_remote:
            cb = self._make_agent_card_cb(name)
            # subscribe_* 同步返回当前 detail，并注册回调供后续实时更新
            detail = await client.subscribe_agent_card(name, version, cb)
            self._subscriptions.append(
                {"kind": "agent_card", "name": name, "version": version, "cb": cb}
            )
        else:
            detail = await client.get_agent_card(
                name, version, cfg.agent_card_registration_type
            )
        self._agent_cards[name] = detail
        logger.info(
            f"Nacos AI 加载 Agent Card 成功: {name} (订阅={cfg.subscribe_remote})"
        )

    async def _load_mcp_server(self, client: NacosAIClient, name: str) -> None:
        """加载（订阅或一次性拉取）单个 MCP Server 并缓存。"""
        cfg = config.nacos_ai
        version = cfg.load_mcp_version
        if cfg.subscribe_remote:
            cb = self._make_mcp_server_cb(name)
            detail = await client.subscribe_mcp_server(name, version, cb)
            self._subscriptions.append(
                {"kind": "mcp", "name": name, "version": version, "cb": cb}
            )
        else:
            detail = await client.get_mcp_server(name, version)
        self._mcp_servers[name] = detail
        logger.info(
            f"Nacos AI 加载 MCP Server 成功: {name} (订阅={cfg.subscribe_remote})"
        )

    # -------------------------------------------------------------------------
    # 订阅回调（SDK 同步调用，detail 作为首参传入；用 *args 容错不同 SDK 版本）
    # -------------------------------------------------------------------------
    def _make_agent_card_cb(self, name: str) -> Callable:
        def _cb(*args: Any) -> None:
            if args:
                self._agent_cards[name] = args[0]
            logger.info(f"Nacos AI Agent Card 订阅更新: {name}")

        return _cb

    def _make_mcp_server_cb(self, name: str) -> Callable:
        def _cb(*args: Any) -> None:
            if args:
                self._mcp_servers[name] = args[0]
            logger.info(f"Nacos AI MCP Server 订阅更新: {name}")

        return _cb

    # -------------------------------------------------------------------------
    # 对外只读访问（经 app_state.nacos_ai 供查询 / 健康检查）
    # -------------------------------------------------------------------------
    @property
    def agent_cards(self) -> Dict[str, Any]:
        return dict(self._agent_cards)

    @property
    def mcp_servers(self) -> Dict[str, Any]:
        return dict(self._mcp_servers)
