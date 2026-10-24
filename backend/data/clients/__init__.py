"""中间件客户端对象集合（对象封装 + 显式容器）。

结构：
- `base.py`：`BaseClient` 统一契约（connect / close / is_connected / raw / health_check）
- `bundle.py`：`ClientBundle` 容器，按名字持有实例（注册于 `app_state.clients`）
- `<middleware>.py`：各中间件客户端类（`PostgresClient` / `RedisClient` / `MilvusClient` /
  `MinioClient` / `NacosClient`），构造参数显式传入，支持多实例与测试注入

用法（各 manager 启动时装配，之后从容器取用）：
    from backend.app_state import app_state
    from backend.data.clients.postgres import PostgresClient

    client = app_state.clients.ensure("postgres",
                                      lambda: PostgresClient.from_settings(app_state.settings.postgres))
    await client.connect()

不再有模块级 `_client` 全局单例，也不再有 `get_client()` / `close()` 模块函数。

注意：本包 __init__ **不**导入子模块（各中间件 SDK 多为软依赖），使用方按需导入具体模块。
"""
__all__ = ["base", "bundle", "postgres", "redis", "milvus", "minio", "nacos"]
