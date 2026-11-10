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
| MCP / 插件 | `backend/mcp/` | `protocol` `registry` `loader` `builtin/` | 存在（§5） |
| RAG 自研 | `backend/rag/` | `loaders`（MinIO 字节解析）/ `splitters`（分块）/ `indexing`（解析入库）/ `retrieval`（混合召回+精排）/ `ranked` | 存在，读写同库闭环 |
| RAG 存储 | `backend/data/milvus/store.py` | `DocumentMilvusStore`（BGE-M3 双向量 + 混合检索 + 按 file_id 删除） | 存在，已接 QA 热路径 |
| 模型工厂 | `backend/common/llm/llm_factory.py` | `LLMFactory`（embed / rerank / classify） | 存在 |
| 消息队列 | `backend/broker/` | `types` `envelope` `topology` `routing` `publish` `outbox_publisher` `consumer` `handlers` `security` | 存在且完整（§6） |
| 业务服务 | `backend/services/` | `agent_run.py` `indexing.py` `notification.py` | 存在，多为 stub（§7） |
| 数据层 | `backend/data/` | `clients/`（postgres/milvus/minio/redis/broker/nacos）、`dao/`（agent/auth/ops/business）、`sql/`（audit.py 原始 SQL）、`postgres/`（ORM 模型，仅生成 DDL）、`milvus/` | 三层齐全 |
| 启动装配 | `backend/server/managers/` `backend/server/register.py` | 各 Manager + 注册顺序 | 存在（§8） |
| 安全 | `backend/security/rbac.py` | 基于 `Scope` 枚举的权限校验 | 存在 |
| 不存在的包 | `backend/core/` `backend/rag/` `backend/plugins/` | 设计蓝图中的三包 | **未落地**，能力已迁移（见上） |

---

## 2. 业务 Agent 实况

四个业务 Agent 的图均已装配并可执行：QA（条件路由）、Resume（线性）、Exam（三轨 + HITL）、Interview（多阶段状态机 + SSE + 报告回写）。Exam 已把三轨批改、汇总、薄弱点和 `interrupt()` 教师复核串成可达图；Interview 用 `checkpointer` 保存多轮状态。

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

### 2.3 exam —— 已落地（线性三轨 + HITL）

`backend/agents/exam/graph.py` `build_exam_graph()` 已装配 9 个节点：

`parse_word → load_questions_meta → run_three_tracks → aggregate_results → analyze_weak_points → notify_teacher → teacher_review → apply_teacher_decision → publish_results`

- `run_three_tracks` 内部并行处理客观题/简答题/代码题；
- `teacher_review` 用 `langgraph.types.interrupt()` 暂停，API 通过 `Command(resume=decision)` 恢复；
- 图绑定统一 `app_state.checkpointer`，thread_id 为 `submission_id`；
- 后端提交/复核/确认接口已接；**前端考试页仍是 mock**。

### 2.4 interview —— 已落地（多阶段状态机 + SSE + 报告）

`backend/agents/interview/graph.py` 已装配 `load_context / check_stage / evaluate_answer / generate_response / generate_report / save_report / save_memory` 七个节点，并绑定统一 `app_state.checkpointer`。阶段流转为 `warmup → tech_base → project → closing → finished`，回答质量驱动追问，结束轮写回五维报告。

- API：`POST /tenant/interview/sessions`、`POST /sessions/{id}/chat`、`POST /sessions/{id}/chat/stream`、`GET /sessions`、`GET /sessions/{id}/report`；
- 流式输出只转发 `generate_response` 节点 token，结束轮直接 `done`；
- Prompt 已接 Nacos `interview_*`；
- 前端「开始面试 / 面试结果 / 面试报告」已接真实接口；历史消息回放、服务端停止生成、删除会话均已闭环。删除采用软删归档，checkpointer 保留可恢复。

---

## 3. 编排层（`orchestration`）

- **AgentRegistry**：`backend/orchestration/agent_registry.py`，`register()` / `get()` / `is_enabled_for_tenant()` / `load_from_db()`（从 `agent` 表 + `agent_capability_policy` 表加载，支持租户级开关）。
- **四 Agent 真实注册**：`backend/server/managers/orchestrator_manager.py` 循环 `for agent_cls in (ResumeAgent, QAAgent, ExamAgent, InterviewAgent): agent_cls().register_into(registry)`。
- **Orchestrator**：`backend/orchestration/orchestrator.py`：
  - `run_agent(agent_type, thread_id, inputs)` → `registry.get()` 取图 → `graph.ainvoke(inputs, configurable={"thread_id": ...})`（**单 agent 直达**）；
  - `run_pipeline(pipeline_plan, ...)` → 顺序 `run_agent` 串联、前输出作后输入（**多 agent 串联**，但**未被统一入口使用**）；
  - `resume(agent_type, thread_id, value)` → 向被 `interrupt()` 挂起的图注入决策；Exam 图已装配，教师复核恢复链路可用。
- **统一入口 unified_chat（已下线）**：原 `backend/api/v1/tenant/chat/unified.py` 已删除，后续整合全部智能体后再做；原实现 `chat()`（`POST /chat`，SSE）：会话归属校验 → 规则前置拦截(零 Token) → `factory.classify`(bert-chinese 粗分) → LLM 路由 → 权限点校验 → `app_state.orchestrator.run_agent(...)`。⚠️ **只走单 agent 直达，未用 `run_pipeline`**；其 LLM 路由是占位实现（注释「真实实现见 M7」，直接把 `general` 兜底成 `qa`）。

---

## 4. RAG（双层适配）

仓库内**自研 RAG 闭环**，读写同库（`agent_rag_docs`），不再委派外部检索服务。
实现参考 `thy-edu-agent/backend/core` 的解析与精排策略，按本项目架构落地：

- **解析/分块** `backend/rag/loaders.py` + `splitters.py`：MinIO 字节 → PDF 逐页 / MD 标题感知 / TXT → **父子片两阶段切分**（参照 `RAG-Ultra`）；全内存、不落盘；`.pdf/.md/.txt` 全支持；父片 1200 字作上下文、子片 300 字参与向量召回，参数由 `QA_PARENT_*` / `QA_CHILD_*` 配置。RAG-Ultra 父片用 BGE 语义切分（需 `langchain_experimental`），本项目未装该依赖，改用已有 `RecursiveCharacterTextSplitter` 大块 + Markdown 标题块，零新增依赖。
- **写入侧** `backend/rag/indexing.py` → `backend/data/milvus/store.py` `DocumentMilvusStore.add_chunks()`：集合只存**子片**（才有 dense+sparse 向量），每片冗余存 `parent_id` / `parent_content`；另有 `chunk_type` / `source_location` / `extra`(JSON) 全部**显式声明**（动态字段无法可靠出现在 `output_fields`）。重新解析前按 `file_id` 删除旧块保证幂等，完成后回写 `agent_file.parse_status=parsed`（失败 `failed` 并由 broker 重试）。由 `qa.parse` 消息触发。
- **读取侧** `backend/rag/retrieval.py` → `DocumentMilvusStore.hybrid_search()`：dense HNSW+IP（写入/查询两侧 L2 归一化）/ sparse `SPARSE_INVERTED_INDEX` 两路召回 + RRF/Weighted 融合，按 `tenant_id` 分区键隔离；再经 `LLMFactory.rerank()` 精排取 Top-K，首条精排分即 `confidence`（精排不可用时降级为粗排 distance）。检索结果按 `parent_id` 分组，用 `<mark>` 在父片原文里高亮所有命中子片。
- **qa 接入**：`agents/qa/nodes.py::retrieve_node` 调 `backend.rag.retrieval.retrieve`；`generate_rag_node` 按父片去重后把**高亮父片**作为上下文，`RAG_ANSWER_PROMPT` 说明 `<mark>` 是命中重点、未标记部分是上下文，以标记部分为主要依据作答。
- **模型封装** `backend/common/llm/llm_factory.py` `LLMFactory`：
  - `bge-m3`：`build_embedder()` 用 `BGEM3EmbeddingFunction`，`embed()` 返回 `{'dense','sparse'}`；
  - `bge-reranker-v2-m3`：`build_reranker()` 用 `BGERerankFunction`，`rerank()` 已实现并被自研检索链路调用；
  - `bert-chinese`：`classify()` 中文意图分类（未配置降级 `general`）。
- ⚠️ **schema 升级**：Milvus 不支持给已有集合加字段。`ensure_collection()` 会用 `describe_collection` 校验必需字段，发现旧集合时 fail-fast 提示调用 `rebuild_collection()`；重建会清空向量，需重新 `/parse` 导入。

---

## 5. 插件机制（`mcp` 模块）

设计文档的「plugins 包」实为仓库的 **`mcp` 模块**（MCP 工具 / 能力注册）。

- **协议/基类**：`backend/mcp/protocol.py`：`AgentPlugin`(Protocol) + `BasePlugin`(ABC) + `BaseTool`(ABC，需实现 `async run(**kwargs)`) + `PluginManifest`。
- **注册表**：`backend/mcp/registry.py` `PluginRegistry`：`register_plugin()`（把插件工具编入 `name→tool` 能力表）、`get_tool()` / `call(timeout=...)`（带超时与 `CapabilityError` 错误边界）。与 `AgentRegistry` 联动：agent 按能力名取工具。
- **发现与装配**：`backend/mcp/loader.py` `discover_builtin()`；装配在 `backend/server/managers/plugin_manager.py`：以 `data/dao/agent/plugin_dao.py` 的启用清单为白名单 → 装配 `PluginRegistry` → 写 `app_state.plugin_registry`，支持 `reload_plugins()` 热更新。
- **内置实现**：`backend/mcp/builtin/web_search/tool.py` `WebSearchTool(name="web_search")`；`backend/mcp/builtin/code_exec/tool.py`。`api/v1/admin/plugins.py` 提供插件管理接口。

---

## 6. 消息队列（`broker`）

- **消息类型枚举**：`backend/broker/types.py` `class TaskType(str, Enum)`：`AGENT_RUN` / `QA_PARSE` / `QA_RAGAS_REVIEW` / `RESUME_REVIEW` / `EXAM_REVIEW` / `NOTIFY_SEND` / `AUDIT_FLUSH`（均为 `task` 工作队列语义；`agent_outbox.message_kind` 由 `routing.Kind` 推导，另预留 `broadcast`）。
- **唯一发消息入口**：`backend/broker/publish.py` `enqueue_task(type, ...)`（只写 `agent_outbox` 表，由 `outbox_publisher.py` 协程异步投递；broker 关时缓冲不丢）。
- **消费者/handler 全映射**：`backend/broker/handlers/__init__.py` 把 7 个 `TaskType` 全部映射到 handler；消费策略在 `backend/broker/consumer/strategies.py`（业务/广播/死信，含幂等与死信落库）。跨副本配置刷新改由 `services/config_refresh.py` 用 Redis 版本号 + 定时拉取实现，不再占用 MQ 消息类型。
- **生产端引用（仓库内实际 `enqueue_task` 的位置）**：
  - `QA_PARSE`：`backend/api/v1/tenant/agent/files.py`（`/parse` 端点上传后入队解析）；
  - `RESUME_REVIEW`：`backend/api/v1/tenant/agent/resume.py:131`；
  - `NOTIFY_SEND`：`backend/server/managers/scheduler_manager.py:118`（HITL 转人工超时提醒）；
  - `EXAM_REVIEW`：`backend/api/v1/tenant/agent/exam.py`（提交试卷后入队批改）；
  - `QA_RAGAS_REVIEW`：`backend/api/v1/tenant/agent/qa_results.py`（问答测评）。
  - ⚠️ `AUDIT_FLUSH` / `AGENT_RUN` 有 handler，但仓库内未找到对应 `enqueue_task` 生产端。
- ⚠️ **broker 默认关闭**：`backend/server/register.py:55` `if config.broker.enabled:` 才注册 `BrokerManager`（默认 `RABBITMQ_ENABLED=false`）；`ObservabilityManager` 亦被注释 `// todo`。

---

## 7. 业务服务层（`services`）

- `backend/services/agent_run.py` `run_long_task(...)`：TODO 接 Orchestrator；`agent_run` 台账尚未写入。
- `backend/services/indexing.py` `parse_document(...)`：已接通 `backend.rag.indexing` → MinIO 读取 → 分块 → BGE-M3 向量化 → Milvus 写入，并回写 `agent_file.parse_status`；失败标 `failed` 并交给 broker 重试。
- `backend/services/notification.py`：`CHANNELS: dict = {}`，`send_notification` 仍只记告警（email/wecom/webhook/ticket 未实现）。
- handler 只做三件事：鉴权、从 `data` 取参数、调 `services/`，并让异常上抛；业务实现全部落在 `services/`，补齐时不需要再改 handler。

---

## 8. 启动装配（`server/managers` + `register`）

`backend/server/managers/` 已具备：checkpointer / fastapi / logging / memory / milvus / model / nacos_* / observability / orchestrator / plugin / postgres / redis / security / broker / scheduler_manager。

`backend/server/register.py` 按 `order` 注册；默认仅注册核心 Manager，**`broker` / `observability` 受配置开关控制，默认不注册**。

---

## 9. 明确未实现清单

1. **面试会话物理清理缺失** — 删除为软删归档，checkpointer 状态保留可恢复；暂无物理清理 checkpoint / 业务行接口。
2. **考试前端未接** — 后端考试图与接口已就绪，但 `dashboard/src/pages/agent/exam/*` 仍是 mock。
3. **通知渠道未实现** — `backend/services/notification.py` `CHANNELS: dict = {}`，`send_notification` 仅记告警。
4. **统一入口已下线** — `backend/api/v1/tenant/chat/unified.py` 已删除，后续整合全部智能体时再实现统一入口与模型路由。
5. **`core` / `rag` / `plugins` 顶层包缺失** — 能力迁移到 `orchestration` / `mcp` / `data`+`common.llm`。
6. **resume 图未绑 checkpointer** — `backend/agents/resume/graph.py` `builder.compile()` 无 checkpointer → 无多轮会话态 / HITL 持久化。
7. **ObservabilityManager 未注册** — `backend/server/register.py` 中仍注释，可观测性未接入。
8. **`agent_run` 台账未写入** — 表与字段已有，但 QA/简历/考试执行完没有写 run/token；看板成功率/占比暂用 API 日志兜底。
9. **业务审计覆盖不全** — `agent_audit_log` 主要覆盖管理动作，QA/简历/文件等业务操作未逐条写审计。
10. **Token 统计缺失** — 尚无 Callback 汇总 prompt/completion tokens；历史消耗只能看模型供应商控制台。

---

## 10. 与旧设计蓝图的偏差小结

| 设计蓝图（v2.3） | 代码实况 |
|---|---|
| `core/` 编排核心包 | 实为 `orchestration/` |
| `rag/` 自研检索包 | 实为 `mcp/retrieval/` + `data/milvus/` + 外部 RAG 服务委派 |
| `plugins/` 插件包 | 实为 `mcp/` 模块（协议/注册/发现） |
| 四 Agent 均按 LangGraph 受控图实现 | qa(条件路由)、resume(线性)、exam(三轨+HITL)、interview(多阶段状态机) 均已落地 |
| 多 Agent 串联 Pipeline 由统一入口调度 | `run_pipeline` 存在但统一入口已下线，当前各 Agent 独立入口 |
| 自研 RAG 全链路召回/重排 | `backend/rag` + Milvus 闭环已接 QA 热路径；embedding/rerank 均在本仓库调用 |
| broker 承载长任务/重索引/通知 | 框架完备；QA parse、resume、exam、RAGAS、通知有生产端，`agent.run`/`audit.flush` 暂无生产端 |
