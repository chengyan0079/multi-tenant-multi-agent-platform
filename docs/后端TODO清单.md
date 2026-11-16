# 后端 TODO / 占位清单

> 代码内不保留 `TODO` 标记，统一记录在此。
> 状态：`未实现` / `占位降级` / `已实现（保留说明）` / `技术说明（非待办）`。
> 最后更新：2026-11-16（业务为 知识问答 / 变更评审 / 变更发布 三个 Agent）。

## 一、功能未实现 / 占位

| 位置 | 内容 | 状态 |
| --- | --- | --- |
| `services/notification.py` | 通知渠道 email / wecom / webhook / ticket 未接真实通道，`send_notification` 仅记日志 | 未实现 |
| `security/security.py` | 违禁词字典为占位，真实清单走配置 / 外部审核插件 | 占位降级 |
| `agents/*/nodes.py`（HITL 通知） | 审批提醒未接 IM（企业微信 / 钉钉 / WebSocket），当前以 DB 状态 + 前端轮询/弹框表达 | 未实现 |
| `server/managers/nacos_ai_manager.py` | Nacos AI（MCP Server 发布）为**半成品**，未纳入主线；`NACOS_AI_ENABLED=false` 时可忽略 | 未完成（非主线） |
| `common/memory/memory.py::push_long` / `agent_long_term_memory.embedding_id` | 长期记忆的语义召回（向量化 + `embedding_id` 回填）未启用，当前按 `block` 类型取最近 N 条 | 预留字段 |
| 会话删除 | 只删 `agent_thread`，`agent_unified_turn` / 评测 / checkpoint 保留（设计如此）；如需「彻底清理」需单独的按租户/时间批量清理入口 | 待建（可选） |

## 二、已实现（保留说明，避免误认为缺失）

| 位置 | 内容 |
| --- | --- |
| `agents/qa/ragas_eval.py` | RAGAS 已改为官方 `ragas.evaluate` + 官方 metrics（失败即 `failed`，不编造分数） |
| `services/long_term_memory_extractor.py` | 长期记忆抽取（LLM + prompt，失败降级为单个 summary 块） |
| `agents/qa/nodes.py::save_memory` / `db_review`、`db_release` 的 `save_memory` 节点 | 三 Agent 均写长期记忆（qa 按摘要阈值；评审/发布在审批或放行后） |
| `mcp/builtin/web_search/tool.py` | 接 Tavily（配置存 `agent_tool.config`，缺省降级） |
| `mcp/builtin/code_exec/tool.py` | provider 可扩展骨架（内置 http provider） |
| `rag/ocr.py` | 扫描件 OCR（RapidOCR 预加载，逐页降级） |
| `common/llm/llm_factory.py` | 思考模式（`thinking` → `extra_body` 透传）、token 估算兜底 |
| `services/agent_run.py` | 已清理（`AGENT_RUN` 死链路删除） |

## 三、技术性说明（非待办）

| 位置 | 内容 |
| --- | --- |
| `data/dao/**` | asyncpg 扩展协议下 `IS NULL + cast` / `ANY` 无法推断参数类型，必须显式 `CAST` |
| `data/dao/agent/thread_dao.py` | `ON CONFLICT DO UPDATE` 仅作占位以触发 `RETURNING`；非法 uuid 直接判「不存在」 |
| `data/dao/business/file_dao.py` | 版本化判定与 `pg_advisory_xact_lock` 并发控制见 `upload` 事务边界 |
| `data/sql/audit.py` | 非请求期写入用 `SYSTEM_USER_ID` 占位审计列 |
| `data/clients/postgres.py` | 三种占位符风格：asyncpg `$1`、psycopg2 `%s`、命名 `:name` |
| `api/v1/tenant/agent/files.py` | 上传结果来自本次内存结果而非 DB 查询，无法走 `fetch_page` |
| `server/managers/security_manager.py` | 认证/护栏在请求期生效，启动项仅校验配置 |
| `server/managers/fastapi_manager.py` | 不在 FastAPI lifespan 做启动，避免与 AppServer 冲突 |
| `server/managers/model_manager.py`、`common/llm/llm_factory.py` | 全局默认 LLM 仅向后兼容，per-agent 走 `get_llm(agent_type)`；本地重模型启动预加载（fail-fast） |
| `api/v1/tenant/graph_states.py` | 明确使用配置 schema 的 `checkpoints` 表，避免历史残留 schema 混淆 |

## 四、抽象方法（`NotImplementedError`，非待办）

`server/base_manager.py`、`agents/base.py`、`mcp/protocol.py`、`data/clients/base.py` —— 抽象基类方法，由子类实现。
