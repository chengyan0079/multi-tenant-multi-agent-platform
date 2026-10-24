"""MinIO（S3 兼容对象存储）客户端对象。

`minio` SDK 为软依赖：安装缺失在真正创建客户端时才报错（给出安装提示），
不会因缺包导致导入失败或启动崩溃。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.data.clients.base import BaseClient, ClientError

if TYPE_CHECKING:
    from backend.config.schemas import MinioSettings


class MinioClient(BaseClient):
    """MinIO 客户端（SDK 同步接口，故 ensure_bucket 为同步方法）。"""

    name = "minio"

    def __init__(
        self,
        endpoint: str,
        *,
        access_key: str,
        secret_key: str,
        secure: bool = False,
        bucket: str = "",
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._secure = secure
        self._bucket = bucket
        self._client: Any | None = None

    @classmethod
    def from_settings(cls, cfg: "MinioSettings") -> "MinioClient":
        return cls(
            cfg.host,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key,
            secure=cfg.secure,
            bucket=cfg.bucket,
        )

    # ---------- 生命周期 ----------
    @property
    def is_connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        if self._client is None:
            try:
                from minio import Minio
            except ImportError as exc:  # 软依赖：真正用到时才要求安装
                raise ClientError(
                    "未安装 minio SDK，无法创建 MinIO 客户端；请执行: pip install minio"
                ) from exc
            self._client = Minio(
                self._endpoint,
                access_key=self._access_key,
                secret_key=self._secret_key,
                secure=self._secure,
            )

    async def close(self) -> None:
        """释放客户端引用（minio SDK 无显式连接池关闭）。"""
        self._client = None

    # ---------- 能力 ----------
    @property
    def raw(self) -> Any:
        if self._client is None:
            raise ClientError("MinioClient 未连接，请先 await connect()")
        return self._client

    def ensure_bucket(self, bucket: str | None = None) -> None:
        """确保桶存在（不存在则创建）。"""
        name = bucket or self._bucket
        if not name:
            raise ClientError("未指定 bucket，且构造时未提供默认 bucket")
        client = self.raw
        if not client.bucket_exists(name):
            client.make_bucket(name)
