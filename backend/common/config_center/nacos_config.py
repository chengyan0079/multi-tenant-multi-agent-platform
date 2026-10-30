"""
nacos_config - Nacos 3.x 配置中心客户端（直连 Open API）

与服务发现（namespace=public）完全独立：本客户端用 config.NACOS_CONFIG_NAMESPACE（默认 agent-platform）。
Nacos 3.x 约定（仅 3.x）：前缀 /nacos/v3，读/写/列/历史走 admin 路径；参数驼峰；
响应包裹在 data 字段，成功码 code=0（不存在返回 code=20004）。

设计要点（对应配置中心对接）：
- 读类（命名空间/配置列表/详情/历史）直连 Nacos，无副作用。
- 写类（publish/remove/rollback）仅在审批通过后调用，带 casMd5 乐观锁防 lost update。
- 历史/当前态以 Nacos 为准，不本地冗余。
实现基于 requests 同步调用，异步侧用 asyncio.to_thread 包裹。
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any

import requests

from backend.common.logger import logger
from backend.config import config


class ConfigCenterError(RuntimeError):
    """配置中心调用异常。"""


class ConfigCenterClient:
    """Nacos 3.x 配置中心 REST 客户端（直连 /nacos/v3 Open API）。"""

    def __init__(
        self,
        server_addr: str | None = None,
        namespace: str | None = None,
        group: str | None = None,
        user: str | None = None,
        password: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.server_addr = (server_addr or config.nacos_config.server_addr).rstrip("/")
        self.namespace = namespace or config.nacos_config.namespace
        self.group = group or config.nacos_config.group
        self.user = user if user is not None else config.nacos_config.user
        self.password = password if password is not None else config.nacos_config.password
        self.timeout = timeout
        self._token: str | None = None
        self._ns_resolved: str | None = None

    def _base(self) -> str:
        return f"{self.server_addr}/nacos/v3"

    def _path(self, action: str) -> str:
        mapping = {
            "get": "/admin/cs/config",
            "publish": "/admin/cs/config",
            "remove": "/admin/cs/config",
            "list": "/admin/cs/config/list",
            "history": "/admin/cs/history/list",
            "history_detail": "/admin/cs/history",
            "namespaces": "/admin/core/namespace/list",
        }
        return f"{self._base()}{mapping[action]}"

    def _ensure_token(self) -> str | None:
        if self._token or not self.user:
            return self._token
        resp = requests.post(
            f"{self.server_addr}/nacos/v3/auth/login",
            data={"username": self.user, "password": self.password},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise ConfigCenterError(f"Nacos 登录失败: {resp.status_code} {resp.text}")
        self._token = resp.json().get("accessToken")
        if not self._token:
            raise ConfigCenterError("Nacos 登录未返回 accessToken")
        return self._token

    def _auth_header(self) -> dict:
        token = self._ensure_token()
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _ns_id(self) -> str:
        """命名空间显示名 → Nacos namespaceId（UUID）。"""
        if self._ns_resolved is not None:
            return self._ns_resolved
        try:
            uuid.UUID(self.namespace)
            self._ns_resolved = self.namespace
            return self._ns_resolved
        except ValueError:
            pass
        try:
            resp = requests.get(self._path("namespaces"), params={},
                                headers=self._auth_header(), timeout=self.timeout)
            for n in (self._check(resp) or []):
                if isinstance(n, dict) and n.get("namespaceShowName") == self.namespace:
                    self._ns_resolved = n["namespace"]
                    return self._ns_resolved
        except Exception:
            pass
        self._ns_resolved = self.namespace
        return self._ns_resolved

    def _query(self, extra: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {"namespaceId": self._ns_id()}
        params.update({k: v for k, v in extra.items() if v is not None})
        return params

    def _check(self, resp: requests.Response) -> Any:
        if resp.status_code != 200:
            raise ConfigCenterError(f"Nacos 返回 {resp.status_code}: {resp.text}")
        text = resp.text.strip()
        if text in ("true", "false"):
            return text == "true"
        try:
            data = resp.json()
        except ValueError:
            return text
        if isinstance(data, dict) and "code" in data:
            if data.get("code") != 0:
                raise ConfigCenterError(f"Nacos 业务错误: {data.get('message')} (code={data.get('code')})")
            payload = data.get("data")
            return payload if payload is not None else True
        return data

    # ---------- 读类 ----------
    def get_config_info(self, data_id: str, group: str | None = None) -> dict | None:
        """获取配置元信息（content/type/md5/createTime/modifyTime）；不存在返回 None。

        列表接口多数版本不返回创建/修改时间，列表页需要时逐条回查本接口补齐。
        """
        params = self._query({"dataId": data_id, "groupName": group or self.group})
        resp = requests.get(self._path("get"), params=params,
                            headers=self._auth_header(), timeout=self.timeout)
        if resp.status_code == 404:
            return None
        try:
            j = resp.json()
        except ValueError:
            text = resp.text.strip()
            return {"content": text} if text else None
        if isinstance(j, dict) and "code" in j:
            if j.get("code") == 0:
                d = j.get("data")
                if isinstance(d, dict):
                    return d
                if isinstance(d, str):
                    return {"content": d}
                return None
            if j.get("code") == 20004:
                return None
            raise ConfigCenterError(f"Nacos 查询失败: {j.get('message')} (code={j.get('code')})")
        text = resp.text.strip()
        return {"content": text} if text else None

    def get_config(self, data_id: str, group: str | None = None) -> str | None:
        """获取当前配置内容；不存在返回 None。"""
        info = self.get_config_info(data_id, group)
        content = info.get("content") if isinstance(info, dict) else None
        return content if isinstance(content, str) else None

    def list_configs(self, data_id: str | None = None, group: str | None = None,
                     page_no: int = 1, page_size: int = 100,
                     with_meta: bool = False) -> dict:
        """配置列表。

        with_meta=True 时对本页每条配置回查详情，补齐创建/修改时间与 type/md5——
        Nacos 各版本的列表接口普遍不返回这些字段。列表页才需要，分组聚合不必传。
        """
        resp = requests.get(self._path("list"), params=self._query({
            "pageNo": page_no, "pageSize": page_size,
            # group 为空表示跨全部分组（与 dataId 空=全部一致）；不能回落到 self.group，
            # 否则只查默认分组，导致其它 group 的配置在列表里“消失”。
            "groupName": group or "", "dataId": data_id or "",
        }), headers=self._auth_header(), timeout=self.timeout)
        data = self._check(resp) or {}
        if with_meta and isinstance(data, dict):
            for it in (data.get("pageItems") or []):
                if isinstance(it, dict):
                    self._fill_config_meta(it)
        return data

    def _fill_config_meta(self, item: dict) -> None:
        """列表项补齐 createTime/modifyTime/type/md5，并统一出 lastModified。"""
        if not (item.get("createTime") and item.get("modifyTime")):
            try:
                info = self.get_config_info(
                    item.get("dataId") or "", item.get("groupName") or self.group
                )
            except Exception:  # noqa: BLE001 - 单条回查失败不影响整个列表
                info = None
            if isinstance(info, dict):
                for key in ("createTime", "modifyTime", "type", "md5", "appName"):
                    if item.get(key) is None and info.get(key) is not None:
                        item[key] = info[key]
        # 前端统一按 lastModified 渲染更新时间；缺失时回落到 modifyTime/createTime
        if not item.get("lastModified"):
            item["lastModified"] = item.get("modifyTime") or item.get("createTime")

    def list_history(self, data_id: str, group: str | None = None,
                     page_no: int = 1, page_size: int = 100) -> dict:
        resp = requests.get(self._path("history"), params=self._query({
            "dataId": data_id, "groupName": group or self.group,
            "pageNo": page_no, "pageSize": page_size,
        }), headers=self._auth_header(), timeout=self.timeout)
        data = self._check(resp) or {}
        for it in (data.get("pageItems") or []):
            if not isinstance(it, dict):
                continue
            # nid：不同 Nacos 版本返回 id 或 nid
            if "nid" not in it and "id" in it:
                it["nid"] = it["id"]
            # 时间：历史列表常见 lastModifiedTime，部分版本为 createdTime
            if not it.get("createdTime"):
                for key in ("lastModifiedTime", "gmtModified", "createTime", "timestamp"):
                    if it.get(key) is not None:
                        it["createdTime"] = it[key]
                        break
            # md5：列表接口通常不返回，用详情补齐；详情无 md5 时按内容计算
            if not it.get("md5"):
                nid = it.get("nid")
                detail = None
                if nid is not None:
                    try:
                        detail = self.get_history(data_id, int(nid), group)
                    except Exception:  # noqa: BLE001 - 单条失败不影响整个列表
                        detail = None
                if isinstance(detail, dict):
                    content = detail.get("content")
                    if detail.get("md5"):
                        it["md5"] = detail["md5"]
                    elif isinstance(content, str) and content:
                        it["md5"] = hashlib.md5(content.encode("utf-8")).hexdigest()
                    if not it.get("createdTime"):
                        it["createdTime"] = detail.get("createdTime") or detail.get("lastModifiedTime")
        return data

    def get_history(self, data_id: str, nid: int, group: str | None = None) -> dict | None:
        resp = requests.get(self._path("history_detail"), params=self._query({
            "dataId": data_id, "groupName": group or self.group, "nid": nid,
        }), headers=self._auth_header(), timeout=self.timeout)
        data = self._check(resp)
        if isinstance(data, dict):
            obj = data.get("data") or data
            # 归一化：详情接口字段名与列表不一致，前端按 nid/createdTime 渲染
            if isinstance(obj, dict):
                if "nid" not in obj and "id" in obj:
                    obj["nid"] = obj["id"]
                if not obj.get("createdTime"):
                    for key in ("lastModifiedTime", "modifyTime", "gmtModified", "createTime", "timestamp"):
                        if obj.get(key) is not None:
                            obj["createdTime"] = obj[key]
                            break
            return obj
        return data

    # ---------- 写类（仅审批通过后调用，带 CAS） ----------
    def publish_config(self, data_id: str, content: str,
                       group: str | None = None, content_format: str = "text",
                       cas_md5: str | None = None) -> bool:
        # content_format 透传为 Nacos type，不做枚举校验（后续新增 toml/ini 等无需改这里）
        data = {
            "namespaceId": self._ns_id(),
            "groupName": group or self.group,
            "dataId": data_id, "content": content, "type": content_format,
        }
        if cas_md5:
            data["casMd5"] = cas_md5
        resp = requests.post(self._path("publish"), data=data,
                            headers=self._auth_header(), timeout=self.timeout)
        result = self._check(resp)
        if isinstance(result, bool):
            return result
        return str(result).strip().lower() == "true"

    def remove_config(self, data_id: str, group: str | None = None,
                      cas_md5: str | None = None) -> bool:
        params = self._query({"dataId": data_id, "groupName": group or self.group})
        if cas_md5:
            params["casMd5"] = cas_md5
        resp = requests.delete(self._path("remove"), params=params,
                               headers=self._auth_header(), timeout=self.timeout)
        result = self._check(resp)
        if isinstance(result, bool):
            return result
        return str(result).strip().lower() == "true"

    def rollback(self, data_id: str, nid: int, group: str | None = None) -> bool:
        """已废弃：回滚改在 service.execute_request 内用申请单已存内容直接发布，便于带 CAS 与记录类型。"""
        hist = self.get_history(data_id, nid, group)
        content = hist.get("content") if isinstance(hist, dict) else None
        if not content:
            raise ConfigCenterError(f"回滚失败：取不到历史内容 data_id={data_id} nid={nid}")
        return self.publish_config(data_id, content, group)


_client: ConfigCenterClient | None = None


def get_config_center_client() -> ConfigCenterClient:
    """懒加载单例客户端。"""
    global _client
    if _client is None:
        if not config.nacos_config.enabled:
            raise ConfigCenterError("Nacos 配置中心未启用（NACOS_CONFIG_ENABLED=False）")
        _client = ConfigCenterClient()
    return _client
