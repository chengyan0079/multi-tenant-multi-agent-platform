"""Nacos 版本适配：服务端 3.x 用 nacos-sdk-python 2.0+，提供命名空间归一与导入提示。"""

from __future__ import annotations

import uuid

from backend.common.logger import logger

_INSTALL_CMD = 'pip install -U "nacos-sdk-python>=2"'


def normalize_namespace_id(namespace: str | None) -> str:
    """Nacos 公共命名空间：控制台显示 'public'，实际 namespaceId 为空串。"""
    if not namespace or namespace == "public":
        return ""
    return namespace


def resolve_namespace_id(
    server_addr: str, namespace: str, username: str = "", password: str = "", timeout: float = 3.0
) -> str:
    """把命名空间解析为 Nacos 3.x 需要的 namespaceId（UUID）。"""
    ns = normalize_namespace_id(namespace)
    if ns == "":
        return ""
    try:
        uuid.UUID(ns)
        return ns
    except ValueError:
        pass
    try:
        import requests

        headers: dict[str, str] = {}
        if username:
            login = requests.post(
                f"{server_addr}/nacos/v3/auth/login",
                data={"username": username, "password": password},
                timeout=timeout,
            )
            if login.status_code == 200:
                token = login.json().get("accessToken")
                if token:
                    headers["Authorization"] = f"Bearer {token}"
        resp = requests.get(
            f"{server_addr}/nacos/v3/admin/core/namespace/list", headers=headers, timeout=timeout
        )
        if resp.status_code == 200:
            for item in resp.json().get("data") or []:
                if isinstance(item, dict) and item.get("namespaceShowName") == ns:
                    return item["namespace"]
    except Exception:
        logger.exception(f"命名空间解析失败，按原值使用: {namespace}")
    return ns


def import_error_hint(feature: str) -> str:
    """from v2.nacos import ... 失败时的提示：区分没装与装的是旧版 1.x。"""
    import importlib.util

    if importlib.util.find_spec("nacos") is not None:
        return (
            f"已安装 nacos-sdk-python 1.x（旧 API：import nacos），不支持 Nacos 3.x 服务端，"
            f"{feature}不可用。请升级：{_INSTALL_CMD}"
        )
    return f"未安装 nacos-sdk-python 2.0+，{feature}不可用（{_INSTALL_CMD}）"
