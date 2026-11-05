# 多租户多智能体协作平台 · 代码实况（架构与实现）

> 本文档描述当前 `backend/` 代码的实际结构与实现状态，供开发与排期使用。设计意图与未落地推演见历史蓝图版本，**本版只记"代码里有什么、缺什么"**。最后更新：2026-11-05。

## 0. 总体形态

- **多模块单应用**：一个 FastAPI 进程，内部按包切分。设计蓝图里的 `core/` / `rag/` / `plugins/` 三个顶层包**未落地**，能力分别拆到了 `orchestration/` / `mcp/` / `data`+`common/llm/`（见 §1）。
- **技术栈**：FastAPI + LangGraph + LangChain + SQLAlchemy(async，全程 `text()` 手写 SQL) + PostgreSQL + Milvus + Redis + RabbitMQ(aio-pika，默认关闭)。
- **工程范式**：`AppServer` + `XXManager`（`register(manager, order)` + 单一 `run()`）；`ConfigManager` 集中加载校验 → `app_state.settings`，其余只消费。
- **多租户**：全链路 `tenant_id`；Milvus partition key、Redis `t:{tenant}:u:{user}:` 前缀、PG 行级隔离；身份上下文缺失时记忆读写直接跳过。

---

## 1. 代码包结构（实际）

| 包 | 路径 | 关键内容 | 状态 |
|---|---|---|---|
| API 装配 | `backend/api/router.py`、`backend/api/v1/__init__.py` | 聚合 admin / auth / tenant 子路由 | 存在 |
| API·admin | `backend/api/v1/admin/` | agents / audit / config_center / files / menu / messages / models / plugins / rbac / tenant / schemas | 齐全 |
| API·auth | `backend/api/v1/auth/router.py` | 登录 / 令牌 / menus / me | 存在 |
| API·tenant | `backend/api/v1/tenant/` | users / roles / audit / messages / agent / knowledge / chat（含 unified） | 存在 |
| 业务 Agent | `backend/agents/{exam,interview,qa,resume}/` | 各含 `agent.py` `graph.py` `nodes.py` `state.py` | 见 §2 |
| 编排 | `backend/orchestration/` | `orchestrator.py` `agent_registry.py` | 存在（§3） |
| MCP / 插件 | `backend/mcp/` | `protocol` `registry` `loader` `retrieval` `builtin/` | 存在（§5） |
| RAG 写入 | `backend/data/milvus/store.py` | `DocumentMilvusStore`（BGE-M3 双向量 + 混合检索） | 存在，未接 QA 热路径 |
| RAG 适配 | `backend/mcp/retrieval/` | `rag_retrieve` / `RagClient`（委派外部服务） | 存在 |
| 模型工厂 | `backend/common/llm/llm_factory.py` | `LLMFactory`（embed / rerank / classify） | 存在 |
| 消息队列 | `backend/broker/` | `types` `envelope` `topology` `routing` `publish` `outbox_publisher` `consumer` `handlers` `security` | 存在且完整（§6） |
| 业务服务 | `backend/services/` | `agent_run.py` `indexing.py` `notification.py` | 存在，多为 stub（§7） |
| 数据层 | `backend/data/` | `clients/`（postgres/milvus/minio/redis/broker/nacos）、`dao/`（agent/auth/ops/business）、`sql/`（audit.py 原始 SQL）、`postgres/`（ORM 模型，仅生成 DDL）、`milvus/` | 三层齐全 |
| 启动装配 | `backend/server/managers/` `backend/server/register.py` | 各 Manager + 注册顺序 | 存在（§8） |
| 安全 | `backend/security/rbac.py` | 基于 `Scope` 枚举的权限校验 | 存在 |
| 不存在的包 | `backend/core/` `backend/rag/` `backend/plugins/` | 设计蓝图中的三包 | **未落地**，能力已迁移（见上） |

---

## 2. 业务 Agent 实况

四个业务 Agent 的**节点函数大多已写**，但**图的装配程度不一**。形态落地小结：设计里宣称的 fan-out/fan-in 三轨并行与 HITL，代码里除 `exam` 节点里写了 `interrupt()` 外，没有任何 agent 真正接成可达图。

### 2.1 qa —— 已落地（LangGraph 受控图）

`backend/agents/qa/graph.py` `build_qa_graph()` 用 `StateGraph(QAState)` 装配 **10 个节点** + 多条 `add_conditional_edges`：

- 意图分类 → `GENERAL` / `PRECISE` / `VAGUE` / `BROAD` 分支；
- 检索后按置信度 `high` / `low_web` / `low_direct` 分流；
- web 搜索后回路由。

形态：**条件路由 + web 兜底 + 记忆落库**；无 fan-out/fan-in、无 HITL。

### 2.2 resume —— 已落地（线性流水线）

`backend/agents/resume/graph.py` `build_resume_graph()` **8 个节点顺序边**：

`upload_to_minio → download_pdf → extract_text → extract_structured → run_six_dimensions → diagnose_issues → generate_summary → save_results`。

形态：**线性流水线**。⚠️ `builder.compile()` **未绑 checkpointer**，无多轮会话态 / HITL 持久化。

### 2.3 exam —— 半完成（节点齐、图未装配）

`backend/agents/exam/nodes.py` 节点函数齐全（含 `human_review` 用 `langgraph.types.interrupt` 做 HITL）；但 `backend/agents/exam/graph.py` 第 23 行 `# todo 图待定`，**全部 `add_node` / `add_edge` 被注释**，编译的是空图。设计里的「三轨并行 fan-out + fan-in 汇总 + HITL」**未接线**。

### 2.4 interview —— 半完成（节点齐、图未装配）

`backend/agents/interview/nodes.py` 含 `init_session` / `ask` / `evaluate` / `respond` / `make_report` / `route_stage`；但 `backend/agents/interview/graph.py` 第 22 行 `# todo 图待定`，**节点/边全注释**。设计里的「状态机 init→question↔evaluate→report→done + SSE 多轮」**未接线**。

---

## 3. 编排层（`orchestration`）

- **AgentRegistry**：`backend/orchestration/agent_registry.py`，`register()` / `get()` / `is_enabled_for_tenant()` / `load_from_db()`（从 `agent` 表 + `agent_capability_policy` 表加载，支持租户级开关）。
- **四 Agent 真实注册**：`backend/server/managers/orchestrator_manager.py` 循环 `for agent_cls in (ResumeAgent, QAAgent, ExamAgent, InterviewAgent): agent_cls().register_into(registry)`。
- **Orchestrator**：`backend/orchestration/orchestrator.py`：
  - `run_agent(agent_type, thread_id, inputs)` → `registry.get()` 取图 → `graph.ainvoke(inputs, configurable={"thread_id": ...})`（**单 agent 直达**）；
  - `run_pipeline(pipeline_plan, ...)` → 顺序 `run_agent` 串联、前输出作后输入（**多 agent 串联**，但**未被统一入口使用**）；
  - `resume(agent_type, thread_id, value)` → 向被 `interrupt()` 挂起的图注入决策（HITL 恢复，因 exam 图未装配故不可达）。
- **统一入口 unified_chat**：`backend/api/v1/tenant/chat/unified.py` `chat()`（`POST /chat`，SSE）：会话归属校验 → 规则前置拦截(零 Token) → `factory.classify`(bert-chinese 粗分) → LLM 路由 → 权限点校验 → `app_state.orchestrator.run_agent(...)`。⚠️ **只走单 agent 直达，未用 `run_pipeline`**；其 LLM 路由是占位实现（注释「真实实现见 M7」，直接把 `general` 兜底成 `qa`）。

---

## 4. RAG（双层适配）

仓库内**不持有完整检索算法**，而是「适配层 + 外部检索服务」双层：

- **仓库内适配层** `backend/mcp/retrieval/`：
  - `adapter.py`：`rag_retrieve(query, tenant_id, top_k)` + `Chunk` 数据类（向 QA 暴露的检索工具）；
  - `client.py`：`RagClient.retrieve()`，三方委派优先级 **MCP 服务(`RAG_MCP_URL`) > 包导入(`core.rag_retriever.retriever.RagRetriever`, `RAG_IMPORT_PATH`) > HTTP(`RAG_HTTP_BASE`)**。
- **索引写入侧（文档→向量库）** `backend/data/milvus/store.py` `DocumentMilvusStore`：`add_chunks()`（BGE-M3 dense+sparse 双向量写入）、`hybrid_search()`（dense HNSW+IP / sparse `SPARSE_INVERTED_INDEX` 两路召回 + RRF/Weighted 融合，按 `tenant_id` 分区键隔离）。**接 Milvus：是**（`AsyncMilvusClient`）。
- **模型封装** `backend/common/llm/llm_factory.py` `LLMFactory`：
  - `bge-m3`：`build_embedder()` 用 `BGEM3EmbeddingFunction`，`embed()` 返回 `{'dense','sparse'}`；
  - `bge-reranker-v2-m3`：`build_reranker()` 用 `BGERerankFunction`，`rerank()` 已实现；
  - `bert-chinese`：`classify()` 中文意图分类（未配置降级 `general`）。
- ⚠️ **接线落差**：`DocumentMilvusStore.hybrid_search` 已实现但**不在 QA 热路径上**（QA 走外部 RAG 服务）；`LLMFactory.rerank` 已定义但**仓库内未被任何检索路径调用**（重排发生在外部检索工程里）。

---

## 5. 插件机制（`mcp` 模块）

设计文档的「plugins 包」实为仓库的 **`mcp` 模块**（MCP 工具 / 能力注册）。

- **协议/基类**：`backend/mcp/protocol.py`：`AgentPlugin`(Protocol) + `BasePlugin`(ABC) + `BaseTool`(ABC，需实现 `async run(**kwargs)`) + `PluginManifest`。
- **注册表**：`backend/mcp/registry.py` `PluginRegistry`：`register_plugin()`（把插件工具编入 `name→tool` 能力表）、`get_tool()` / `call(timeout=...)`（带超时与 `CapabilityError` 错误边界）。与 `AgentRegistry` 联动：agent 按能力名取工具。
- **发现与装配**：`backend/mcp/loader.py` `discover_builtin()`；装配在 `backend/server/managers/plugin_manager.py`：以 `data/dao/agent/plugin_dao.py` 的启用清单为白名单 → 装配 `PluginRegistry` → 写 `app_state.plugin_registry`，支持 `reload_plugins()` 热更新。
- **内置实现**：`backend/mcp/builtin/web_search/tool.py` `WebSearchTool(name="web_search")`；`backend/mcp/builtin/code_exec/tool.py`。`api/v1/admin/plugins.py` 提供插件管理接口。

---

## 6. 消息队列（`broker`）

- **消息类型枚举**：`backend/broker/types.py` `class TaskType(str, Enum)`：`AGENT_RUN` / `DOC_PARSE` / `RESUME_REVIEW` / `KNOWLEDGE_REINDEX` / `NOTIFY_SEND` / `AUDIT_FLUSH` / `CONFIG_REFRESH`。
- **唯一发消息入口**：`backend/broker/publish.py` `enqueue_task(type, ...)`（只写 `agent_outbox` 表，由 `outbox_publisher.py` 协程异步投递；broker 关时缓冲不丢）。
- **消费者/handler 全映射**：`backend/broker/handlers/__init__.py` 把 7 个 `TaskType` 全部映射到 handler；消费策略在 `backend/broker/consumer/strategies.py`（业务/广播/死信，含幂等与死信落库）。
- **生产端引用（仓库内实际 `enqueue_task` 的位置）**：
  - `DOC_PARSE`：`backend/api/v1/admin/files.py:221`（上传后入队解析）；
  - `RESUME_REVIEW`：`backend/api/v1/tenant/agent/resume.py:131`；
  - `NOTIFY_SEND`：`backend/server/managers/scheduler_manager.py:118`（HITL 转人工超时提醒）；
  - `CONFIG_REFRESH`：`backend/broker/publish.py:57`（跨副本刷新注册表）。
  - ⚠️ `AUDIT_FLUSH` / `AGENT_RUN` / `KNOWLEDGE_REINDEX` 有 handler，但**仓库内未找到对应 `enqueue_task` 生产端**。
- ⚠️ **broker 默认关闭**：`backend/server/register.py:55` `if config.broker.enabled:` 才注册 `BrokerManager`（默认 `RABBITMQ_ENABLED=false`）；`ObservabilityManager` 亦被注释 `// todo`。

---

## 7. 业务服务层（`services`）

- `backend/services/agent_run.py` `run_long_task(...)`：TODO 接 Orchestrator。
- `backend/services/indexing.py` `parse_document(...)`：仅 `logger.warning(...)` 并把文件标 `failed`；`reindex_knowledge(...)` 仅告警。**即 `DocumentMilvusStore.add_chunks` 写入链路未接通**。
- `backend/services/notification.py`：`CHANNELS: dict = {}`，注释 `TODO(notify.send)`；`send_notification` 仅记告警（email/wecom/webhook/ticket 未实现）。
- handler 只做三件事：鉴权、从 `data` 取参数、调 `services/`，并让异常上抛；业务实现全部落在 `services/`，补齐时不需要再改 handler。

---

## 8. 启动装配（`server/managers` + `register`）

`backend/server/managers/` 已具备：checkpointer / fastapi / logging / memory / milvus / model / nacos_* / observability / orchestrator / plugin / postgres / redis / security / broker / scheduler_manager。

`backend/server/register.py` 按 `order` 注册；默认仅注册核心 Manager，**`broker` / `observability` 受配置开关控制，默认不注册**。

---

## 9. 明确未实现清单

1. **exam 图未装配** — `backend/agents/exam/graph.py:23` `# todo 图待定`，`add_node/add_edge` 全注释 → 编译空图，三轨并行 + HITL 不可达。
2. **interview 图未装配** — `backend/agents/interview/graph.py:22` `# todo 图待定`，同上 → 状态机 / SSE 多轮不可达。
3. **文档解析 / 知识回流未接入** — `backend/services/indexing.py:23` `parse_document` 仅告警并标 `failed`；`reindex_knowledge` 仅告警。
4. **通知渠道未实现** — `backend/services/notification.py:30` `CHANNELS: dict = {}`，`send_notification` 仅记告警。
5. **统一入口 LLM 路由占位** — `backend/api/v1/tenant/chat/unified.py:101-104` 注释「占位 LLM 路由；真实实现见 M7」，直接把 `general` 兜底成 `qa`。
6. **`core` / `rag` / `plugins` 顶层包缺失** — 能力迁移到 `orchestration` / `mcp` / `data`+`common.llm`。
7. **resume 图未绑 checkpointer** — `backend/agents/resume/graph.py:45` `builder.compile()` 无 checkpointer → 无多轮会话态 / HITL 持久化。
8. **rerank 在仓库内未被调用** — `common/llm/llm_factory.py` `rerank()` 已实现，但 QA 检索走外部 RAG 服务，内部 `DocumentMilvusStore.hybrid_search` 亦不在 QA 热路径。
9. **ObservabilityManager 未注册** — `backend/server/register.py:51` 注释 `// todo`，可观测性未接入。
10. **HITL 休眠** — `interrupt()` 仅写于 `backend/agents/exam/nodes.py:55`，因 exam 图未装配而永不触发；统一入口与 `Orchestrator.resume` 已就绪但无可达图。

---

## 10. 与旧设计蓝图的偏差小结

| 设计蓝图（v2.3） | 代码实况 |
|---|---|
| `core/` 编排核心包 | 实为 `orchestration/` |
| `rag/` 自研检索包 | 实为 `mcp/retrieval/` + `data/milvus/` + 外部 RAG 服务委派 |
| `plugins/` 插件包 | 实为 `mcp/` 模块（协议/注册/发现） |
| 四 Agent 均按 LangGraph 受控图实现 | qa(条件路由)、resume(线性) 已落地；exam、interview 节点齐但图未装配 |
| 多 Agent 串联 Pipeline 由统一入口调度 | `run_pipeline` 存在但统一入口只用单 agent 直达 |
| 自研 RAG 全链路召回/重排 | 仓库内仅适配层 + Milvus 写入；实际召回/重排委托外部服务 |
| broker 承载长任务/重索引/通知 | 框架完备，默认关闭；业务消费体多为 stub，部分 TaskType 无生产端 |
