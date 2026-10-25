# 多 Agent 系统架构设计方案

> 版本：v2.3 ｜ 日期：2026-10-22 ｜ 作者：CTO 助手（hm-cto）
> 业务蓝本：EduAgent —— 教育场景的 AI 多智能体辅助平台（参考 `F:\heima\黑马课程文件\...\02.EduAgent\官方文档`）
> 范围：以 EduAgent 业务场景为蓝本，设计一套**多模块、单应用**的多 Agent 编排系统；覆盖 LangGraph 图编排、插件化能力缝隙、分层记忆与 RAG 复用、状态外置与水平扩展。本方案与《智能体平台 · 问答系统（FAQ+RAG）架构设计 v6.2》互为补充：RAG 能力直接复用既有 **rag-ultra** 项目，不重复造轮子。

---

## 0. 背景、约束与关键决策

### 0.1 业务场景（EduAgent 四大 Agent）

| Agent | 范式 | 核心流程 | 原课程入口 |
|---|---|---|---|
| 简历审查 | 并行评审（六维度 fan-out/fan-in） | PDF 解析→结构化提取→六维度并行评分→问题诊断→整体评价→持久化 | `POST /resume/...` |
| 智能问答 | RAG（检索增强 + 记忆） | 意图分类→查询改写/HyDE→混合检索→重排→按置信度生成/Web兜底→存记忆 | `POST /qa/...` |
| 试卷批改 | Human-in-the-Loop | Word 解析→题目元数据加载→三轨并行（客观规则/简答 LLM/代码 LLM）→汇总→HITL→教师确认发布 | `POST /exam/...` |
| 模拟面试 | 状态机 + SSE 多轮 | 会话初始化→阶段推进→回答质量评估→面试官回应→报告生成→记忆保存 | `POST /interview/...` |

四类业务的**流程形状根本不同**，按业务边界拆分（高内聚、低耦合），每个 Agent 可独立开发、测试、升级。系统采用「**受控工作流 + 多 Agent 编排**」：每个 Agent 内部是 LangGraph 显式画出的带分支/条件的受控图，四个 Agent 之上由 Orchestrator 统一调度（强调可控可预测，而非完全自主）。

### 0.2 已确认约束（本次修订四大决策）

| 项 | 决策 | 说明 |
|---|---|---|
| ① 形态 | **多模块、单应用**（非多服务） | 一个 FastAPI 应用 `backend/`，内部按 `server/core/agents/api/rag/plugins/config/models/middleware` 分包；不再拆 `ap-ingress`/`ap-agent`/`ap-rag` 等多服务。开发/部署/调试简单，契合课程单体结构，且仍保留水平扩展能力（无状态 + 外置状态） |
| ② 向量库 | **Milvus**（不用 PGVector） | BGE-M3 dense+sparse 同集合、Hybrid（WeightedRanker）召回、bge-reranker-v2-m3 精排；partition key 做租户隔离。初期即上 Milvus，不再以 PGVector 过渡 |
| ③ 模型 | **bge-m3 + bge-reranker-v2-m3 + bert-chinese + LLM** | bge-m3 向量化、bge-reranker-v2-m3 重排、bert-chinese 做中文意图/文本分类（替代原 google-bert / Query Classifier）、LLM 负责生成与复杂路由 |
| ④ RAG | **复用 rag-ultra，不重建** | RAG 检索/索引/精排能力直接来自既有 `RAG-Ultra` 工程（`E:\cywork\python\project\RAG-Ultra`），本系统仅提供**集成适配层**将其暴露为工具/能力，不重写检索管线 |

### 0.3 其余已确认约束

- **运行时**：FastAPI + LangGraph + LangChain + SQLAlchemy(async，`text()` 手写 SQL) + PostgreSQL + Milvus + Redis。
- **工程范式**：复用 `AppServer` + `XXManager`（`register(manager, order)` + 单一 `run()`）、`ConfigManager` 集中加载校验 → `app_state.settings`，其余只消费。
- **模型工厂**：`LLM Factory`（3.4）统一封装 LLM / Embedding / Reranker / 分类器，三层兜底 + 重试（3.5）。
- **多租户**：全链路 `tenant_id`；Milvus partition key、Redis `t:{tenant}:u:{user}:` 前缀、PG 行级隔离。
- **可观测**：结构化 JSON 日志全程 `trace_id`；LLM/工具/图转移轨迹进 Langfuse（自托管）。
- **运行环境**：conda `agent_platform`（Python 3.12）；提交/推送由 CEO 控制（项目铁律）。

---

## 1. 设计目标

- **多模块单应用**：以包（module）而非服务（service）切分；统一入口 + 编排器 + 四个 Agent 模块 + RAG 适配 + 插件缝隙，全部进程内协作。
- **图编排**：每个 Agent 用 LangGraph 的 State/Node/Edge/Checkpointer 四要素实现受控工作流；支持分支、并行（fan-out/fan-in）、循环、HITL 暂停恢复。
- **插件化能力缝隙**：工具/能力以协议驱动注册，单能力故障不影响整体；新增能力=新增模块，不改编排核心。
- **模型分工明确**：bge-m3（向量）、bge-reranker-v2-m3（精排）、bert-chinese（中文意图/分类快路径）、LLM（生成 + 复杂路由）。
- **RAG 复用**：直接接入 rag-ultra，避免重复建设检索/索引/精排。
- **状态外置 + 无状态**：PostgreSQL（checkpointer + 业务 + 记忆元数据）+ Milvus（向量）+ Redis（会话/缓存/队列/HITL）；应用无本地状态 → 多副本水平扩展。
- **安全与多租户**：输入护栏（注入/违禁词）、输出护栏、认证、租户隔离贯穿全链路；HITL 转人工不幻觉、不越权。

---

## 2. 总体架构（多模块单应用 + 分层）

```
                    多 Agent 系统（EduAgent 业务蓝本）
        ┌──────────────────────────────────────────────────────────┐
        │  接入层  backend/api/v1                                   │
        │   unified_chat(统一入口: 前置拦截→意图路由→SSE分发)         │
        │   + /resume /qa /exam /interview 各 Agent 直连端点          │
        └───────────────────────────┬──────────────────────────────┘
                                     │ capability / agent_type
        ┌────────────────────────────▼─────────────────────────────┐
        │  编排层  backend/core/orchestrator.py                      │
        │  单 Agent 直达 │ 多 Agent 串联 Pipeline(简历→面试等)        │
        │  AgentRegistry(模块注册/发现/隔离)                          │
        └───────────────────────────┬──────────────────────────────┘
            ┌──────────────┬─────────┴──────────┬──────────────────┐
            ▼              ▼                    ▼                  ▼
   ┌─────────────┐ ┌─────────────┐     ┌──────────────┐  ┌────────────────┐
   │ agents/     │ │ agents/     │     │ agents/      │  │ agents/        │
   │ resume      │ │ qa          │     │ exam         │  │ interview      │
   │ (LangGraph) │ │ (LangGraph) │     │ (LangGraph)  │  │ (LangGraph)    │
   └──────┬──────┘ └──────┬──────┘     └──────┬───────┘  └───────┬────────┘
          │ 工具/能力调用    │                  │                  │
        ┌─▼─────────────────▼──────────────────▼──────────────────▼─┐
        │  能力缝隙层  backend/plugins + backend/rag(adapter→rag-ultra)│
        │  rag_retrieve │ web_search │ code_exec │ pdf/word_parse     │
        └───────────────────────────┬──────────────────────────────┘
                                     │
        ┌────────────────────────────▼─────────────────────────────┐
        │  模型与基础设施层  backend/core                             │
        │  llm_factory(LLM/bge-m3/bge-reranker-v2-m3/bert-chinese)  │
        │  memory(短期Redis/长期PG/语义Milvus) │ security │ config    │
        └────────────────────────────┬─────────────────────────────┘
        ┌────────────────────────────▼─────────────────────────────┐
        │  存储层  PostgreSQL(checkpointer+业务+记忆) │ Milvus(向量)   │
        │          │ Redis(会话/缓存/队列/HITL)  │ SQLAlchemy(async)  │
        └───────────────────────────────────────────────────────────┘
        贯穿：安全治理（输入/输出护栏·认证）· 多租户(tenant_id) · Langfuse 可观测
```

### 2.1 模块划分（多模块，非多服务）

| 包 | 职责 | 关键技术 |
|---|---|---|
| `backend/server` | **服务启动器**：`AppServer` + 各 `XXManager`（logging/redis/postgres/checkpointer/milvus/model/memory/plugin/rag_adapter/orchestrator/observability/security/fastapi）；统一 `register(manager, order)` + 单一 `run()`，依赖顺序启动、优雅启停、fail-fast | AppServer、BaseManager、ConfigManager |
| `backend/config` | `ConfigManager`：env/YAML + Pydantic 校验 → `app_state.settings`；全应用配置唯一来源 | Pydantic v2、pydantic-settings |
| `backend/core` | 编排内核：Orchestrator（单 Agent 直达 / 多 Agent 串联）、AgentRegistry、LLM 工厂、记忆抽象、安全护栏、异常体系、trace 封装 | LangGraph、LLM Factory |
| `backend/agents/resume` | 简历审查 Agent（六维度并行 fan-out/fan-in 图） | LangGraph、PDF 解析、bert-chinese 维度标注 |
| `backend/agents/qa` | 智能问答 Agent（RAG 图，复用 rag-ultra） | LangGraph、rag 适配层、记忆 |
| `backend/agents/exam` | 试卷批改 Agent（三轨并行 + HITL 图） | LangGraph、Word 解析、规则引擎 |
| `backend/agents/interview` | 模拟面试 Agent（状态机 + SSE 图） | LangGraph、状态机、LLM 生成 |
| `backend/rag` | **rag-ultra 集成适配层**（不重建，仅适配）：`adapter.py` 暴露 `rag_retrieve()`，`client.py` 接入 RAG-Ultra | 调用/导入 RAG-Ultra 检索与索引能力 |
| `backend/plugins` | **插件管理**：能力缝隙。`protocol.py`(AgentPlugin 协议)、`registry.py`(运行时注册表)、`loader.py`(扫描 `backend/plugins` + entry-points)、`builtin/`(web_search/code_exec 等，每插件含 `manifest.yaml`)、`external/`(外部插件挂载点) | Protocol + Registry + BaseTool、错误边界 |
| `backend/data/postgres` | 表结构模型：按 `auth` / `agent` / `business` / `ops` 分域，含 thread/run/message/plugin/tool/escalation/memory/audit 及 `business/` 各 Agent 元数据。**仅供 `scripts/gen_schema.py` 生成 DDL，运行期不加载** | SQLAlchemy 2.x async（仅 DDL） |
| `backend/data/sql` + `backend/data/dao` | 运行时数据访问：`session_scope`、`fetch_*` 助手、审计列注入；DAO 里 SQL 全部 `text()` 手写，结果映射为 dict | SQLAlchemy 2.x async + `text()` |
| `backend/middleware` | 接入层中间件：认证（`get_current_user`）、trace_id 注入、租户级限流 | FastAPI middleware |
| `backend/api/v1` | 统一入口（unified_chat）+ 各 Agent 直连端点 + orchestrator/threads/plugins/escalations 运维端点；前置拦截、意图路由、SSE 分发 | FastAPI、Pydantic v2、sse-starlette、slowapi |

### 2.2 技术栈

| 层 | 选型 |
|---|---|
| 服务框架 | FastAPI + Pydantic v2 + asyncio + SSE（sse-starlette） |
| 编排 | **LangGraph**（StateGraph + checkpointer + interrupt）+ LangChain（LLM/Tool 抽象） |
| 配置 | `ConfigManager`（env + 可选 YAML，Pydantic 校验）→ `app_state.settings` |
| 数据访问 | **SQLAlchemy 2.x async**（`AsyncEngine` + `asyncpg`），**不用 ORM 映射**：SQL 用 `text()` 手写，DAO 返回 `dict`；模型类只给建库脚本用 |
| 状态/业务/记忆 | **PostgreSQL 15+**（`AsyncPostgresSaver` checkpointer + 业务表 + 长期记忆） |
| 向量 | **Milvus 2.4+**（BGE-M3 dense 1024 + sparse，Hybrid/WeightedRanker，partition key 隔离） |
| 缓存/会话/队列/HITL | Redis |
| 模型 | LLM（平台网关/OpenAI 兼容）；**bge-m3**（嵌入）；**bge-reranker-v2-m3**（重排）；**bert-chinese**（中文意图/文本分类） |
| RAG | **复用 rag-ultra**（BGE-M3 + Milvus + WeightedRanker + Reranker + Memory） |
| 可观测 | Langfuse（自托管）、Prometheus、JSON 日志（trace_id） |

---

## 3. 编排运行时（LangGraph per-Agent + Orchestrator）

### 3.1 每个 Agent 是一张受控图

统一套路：**定义 State（TypedDict）→ 写若干节点 → 用边（含条件边）连起来 → 绑定 Checkpointer → compile()**。

- **State**：所有节点共享的数据结构（消息、下一步、活跃 Agent、中间结果、tenant_id、trace_id、metadata）。
- **Node**：读 State、做一件事（调模型/检索/打分/解析）、返回要更新的字段。
- **Edge / 条件边**：`add_conditional_edges` 按 State 动态分支（问答按问题类型、批改按题型、面试按阶段）。
- **Checkpointer**：`AsyncPostgresSaver` 持久化 State，支持多轮记忆与 `interrupt()` 暂停恢复（HITL）。

### 3.2 Orchestrator（编排器，单应用内）

`backend/core/orchestrator.py` 是系统「前台 + 调度员」，不亲自干活，但知道每件事该找谁：

- **单 Agent 直达**：识别意图 → 直调对应 Agent 图（`build_resume_graph` / `build_qa_graph` / `build_exam_graph` / `build_interview_graph`）。
- **多 Agent 串联 Pipeline**：复杂场景把多个 Agent 串成流水线（如「简历审查 → 模拟面试」：简历输出作为面试上下文；「问答 → 试卷批改」跨能力协作），前一个输出作为后一个输入。
- **AgentRegistry**：各 Agent 模块启动时 `register(agent_type, build_graph, schema)`，运行时按 `agent_type` 取图；支持能力开关与隔离。

### 3.3 执行模式（来自课程第 8 章）

| 模式 | 触发 | 行为 |
|---|---|---|
| 单 Agent 直达 | 意图明确 | 直接路由到对应 Agent 图 |
| 多 Agent 串联 | 复杂任务 | 按 `pipeline_plan` 顺序串联多 Agent，SSE 推送 `pipeline_plan` 事件 |

### 3.4 HITL / 转人工

试卷批改等高风险动作前 `interrupt(reason)` 挂起，写入 HITL 队列（`escalations` / Redis `t:{tenant}:u:{user}:hitl`），教师确认后 `resume(thread_id, value)` 继续；不强行自动发布。

---

## 4. 模型与推理（四模型分工）

`backend/core/llm_factory.py` 统一封装，三层兜底 + 重试：

| 模型 | 角色 | 用途 |
|---|---|---|
| **bge-m3** | 嵌入 | 文档块/查询向量化（dense 1024 + sparse）；RAG 检索与语义记忆召回共用 |
| **bge-reranker-v2-m3** | 重排 | RAG 检索结果精排 + 语义记忆召回精排；输出置信度用于分支 |
| **bert-chinese** | 中文意图/文本分类（快路径） | ① 统一入口「五类零 Token 回复」前置拦截（关键词/正则精确匹配）② 意图粗分（问答/批改/面试/简历/通用）③ 结构化分类（简历维度标注、题型检测）|
| **LLM** | 生成 + 复杂路由 | 各 Agent 的生成节点；歧义意图的 LLM 路由（DeepSeek 直接分类，无本地模型兜底）|

> 意图路由采用「**bert-chinese 快路径 + LLM 兜底**」双轨：高频/确定意图由 bert-chinese 零 Token 即时分类，模糊意图交 LLM 路由（呼应课程 8.4「LLM 路由而非本地模型」的同时，落实你对 bert-chinese 的指定）。

---

## 5. 存储与数据模型（PostgreSQL + Milvus + Redis）

### 5.1 存储分工

| 数据 | 存储 | 说明 |
|---|---|---|
| LangGraph checkpoints / writes | PostgreSQL | `AsyncPostgresSaver.setup()` 自动建表，状态外置 |
| 业务/审计/长期记忆/插件目录/人工队列 | PostgreSQL | SQLAlchemy + `text()` 手写 SQL（DAO 层） |
| 向量（dense + sparse） | **Milvus** | BGE-M3，partition key = tenant_id；Hybrid（WeightedRanker）召回 |
| 会话窗口/答案缓存/队列/限流/HITL | Redis | `t:{tenant}:u:{user}:` 前缀 |

### 5.2 核心表字段清单

> 完整结构以《数据库设计文档》为准；模型类在 `backend/data/postgres/`（按 `auth` / `agent` / `business` / `ops` 分域），只服务于 `scripts/gen_schema.py` 生成 DDL，运行期不加载。

```text
AgentThread          一次会话/任务
    id / tenant_id / user_id / status / graph_name / create_at / updated_at

AgentRun             运行台账（token/成本/延迟）
    id / tenant_id / user_id / thread_id / graph_name / status
    prompt_tokens / completion_tokens / cost_cents / started_at / ended_at

AgentMessage         append-only 轨迹（replay/fork）
    id / tenant_id / user_id / thread_id / run_id / role / type / payload(JSON) / create_at

AgentPlugin          能力/插件注册表
    name / version / capabilities(JSON) / status / config(JSON) / registered_at

AgentTool            工具目录
    name / plugin / description / schema(JSON)

AgentEscalation      HITL / 转人工队列
    id / tenant_id / user_id / thread_id / reason / status / assigned_user_id / resolved_at

AgentLongTermMemory  长期记忆（Letta 式分页）
    id / tenant_id / user_id / agent_id / block / content / embedding_id

AgentAuditLog        审计
    id / tenant_id / user_id / action / target / detail(JSON) / create_at / updated_at
```

> 业务表（简历/问答/批改/面试各自的元数据）按 EduAgent 第 3 章建表规范落地，与上式共用同一 PostgreSQL 实例、按 `tenant_id` 行级隔离。

---

## 6. 记忆与 RAG 集成（rag-ultra 复用）

### 6.1 分层记忆

| 层 | 存储 | 内容 | 访问 |
|---|---|---|---|
| 短期 | Redis `t:{tenant}:u:{user}:session:{thread_id}` | 滚动窗口最近消息（多轮上下文） | memory 模块 |
| 长期 | PostgreSQL `agent_memory` | Letta 式分页记忆块（人设/事实/偏好/摘要） | memory 模块 |
| 语义 | Milvus |  episodic / 语义片段向量（partition key=tenant_id） | memory 模块 |

### 6.2 RAG 复用（关键：不重建）

`backend/rag/` 是 **rag-ultra 的集成适配层**，不重写检索管线：

- **索引/写入侧**：复用 rag-ultra 的文档读取、智能分块、BGE-M3 嵌入、Milvus 写入（Hybrid/WeightedRanker）能力；本系统仅在做「建库」类任务时调用其索引接口。
- **查询侧**：适配层暴露 `rag_retrieve(query, tenant_id, top_k) -> List[Chunk]` 工具，内部调用 rag-ultra 的混合召回 + bge-reranker-v2-m3 精排；qa Agent 的 `retrieve` 节点直接消费该工具。
- **记忆联动**：qa Agent 的 Memory（5.9）与 rag-ultra 的对话记忆解耦——本系统负责会话级短期/长期记忆，rag-ultra 负责知识库检索；两者通过适配层协作，互不侵入。
- **依赖边界**：rag-ultra 为独立工程（`E:\cywork\python\project\RAG-Ultra`），本系统通过包导入或 HTTP 调用接入，禁止把其检索代码复制进本仓库（避免双份维护）。

---

## 7. 意图路由与前置拦截（bert-chinese + LLM）

统一入口 `backend/api/v1/chat/unified.py` 的请求生命周期（全程 SSE 流式）：

```
用户一句话
   │
   ▼
[1] 规则前置拦截（零 Token）：五类社交/元场景精确匹配（关键词集合 + 正则）→ 直接回复
   │ 未命中
   ▼
[2] bert-chinese 意图粗分：resume / qa / exam / interview / general（快路径，低延迟）
   │ 模糊/低置信
   ▼
[3] LLM 路由：DeepSeek 直接分类 → agent_type + execution_mode + confidence
   │
   ▼
[4] Orchestrator 分发：单 Agent 直达 或 多 Agent 串联 Pipeline
   │
   ▼
[5] SSE 事件流：routing_decision → progress → token/guidance → pipeline_plan → meta → done
```

SSE 事件类型：`routing_decision` / `progress` / `token` / `guidance` / `pipeline_plan` / `meta` / `done` / `error`。

---

## 8. 插件化 / 模块缝隙（capability seams）

- **协议**：每个能力/工具实现统一 `AgentPlugin` 协议（`name/version/capabilities/register()/get_tools()/health()`），注册进 `AgentRegistry`。
- **发现与隔离**：启动时扫描 `backend/plugins/` + entry-points；单能力异常被运行时捕获（错误边界），**单能力故障不影响整体**；每个工具设超时与熔断。
- **现有能力映射**：

| 能力 | 模块 | 说明 |
|---|---|---|
| `rag_retrieve` | `backend/rag` (→ rag-ultra) | 检索工具，qa Agent 消费 |
| `web_search` | `backend/plugins` | 联网兜底（低置信问答） |
| `pdf_parse` | `backend/agents/resume` | 简历 PDF 解析 |
| `word_parse` | `backend/agents/exam` | 试卷 Word 解析 |
| `code_exec` | `backend/plugins` | 代码题沙箱评估（规划） |

- **append-only 轨迹**：所有 message/tool_call/state_transition 写入 `agent_messages`（不可变），支持 replay 与 fork（调试/回归/人工接管）。

---

## 9. 安全与多租户（贯穿）

| 维度 | 机制 |
|---|---|
| 租户隔离 | 全链路 `tenant_id`；PG 行级过滤；Milvus partition key；Redis `t:{tenant}:u:{user}:session:{thread}` 前缀 |
| 输入护栏 | 接入层 DFA 违禁词 + Prompt 注入防护 + 长度校验 |
| 输出护栏 | 生成后违禁词/泄露二次过滤 |
| 认证 | `backend/middleware/auth.py` 依赖注入 `get_current_user` |
| 审计 | 工具调用、HITL、租户开关变更写入 `agent_audit_log` |
| 防幻觉/越权 | 低置信度/高风险 → `interrupt()` 转人工，不自动执行 |

### 9.0 租户模型与业务语义（在 EduAgent 蓝本中怎么理解）

**一句话**：在本蓝图中，**租户（Tenant）= 一个独立的教育组织**（学校 / 培训机构 / 企业大学 / 院系），是系统内**数据、配置、用户与资源的最高隔离边界**。同一套代码实例服务 N 个租户，彼此互不可见——这正是「多租户」作为平台级能力的意义。

**① 三层概念：租户 vs 用户 vs 角色**

| 概念 | 含义 | EduAgent 示例 |
|---|---|---|
| **租户 Tenant** | 组织单位（隔离边界） | 「成都七中」「新东方雅思部」「某公司企业大学」各为一个租户 |
| **用户 User** | 具体的人，归属于某租户 | 学生张三、教师李老师 |
| **角色 Role** | 用户在租户内的职能权限 | `student` / `teacher` / `tenant_admin` / `admin` |

- 一个用户通过 `agent_user_tenant` 可**同时属于多个租户**（如李老师既在「七中」任教师，又在「培训部」任 tenant_admin），但**同一租户内只保留一个角色**（表主键 `(user_id, tenant_id)` 强制）；跨租户换角色靠在登录请求里指定 `tenant_id` 实现（换租户 = 重新登录），不是一次请求内叠加多角色，也不做会话内切换。
- 鉴权产出的 `tenant_id` 是后续所有隔离的**根键**（见 §9.1 ②）。

**② 一个租户内部包含什么**

- 人员：学生 / 教师 / 管理员
- 组织单位：班级（class）、专业、年级
- 业务数据资产：知识库（QA 文档）、人才库（简历库）、题库（试卷 / 面试）、学生作品与答卷
- 配置面：提示词模板、模型配额、插件 / 能力开关、HITL 策略、评分 rubric

**③ 四大 Agent 的租户数据边界（具体隔离物）**

| Agent | 每个租户**独立私有**的资产 |
|---|---|
| 简历审查 | 人才库、简历库、六维度评分配置、报告模板 |
| 智能问答 | Milvus partition（知识库 / FAQ 向量），查询只命中本租户 |
| 试卷批改 | 题库、试卷、答卷、判分规则 |
| 模拟面试 | 题库、面试官人设、面试报告 |

**④ 租户隔离 = 不仅隔离数据，还隔离配置**

- **数据隔离**：PG `tenant_id` 行级 + Milvus partition key + Redis `t:{tenant}:u:{user}:` 前缀（§9.1 ②）。
- **配置隔离**：某租户未开通「模拟面试」→ `agent_capability_policy` 关闭，Orchestrator 路由直接拒答（§9.1 ④）；模型配额 / 提示词模板 / 评分 rubric / HITL 策略均按租户存读，互不串台。
- 效果：**一套部署同时服务多所机构，每家看到的是完全私有的空间**，且功能开通、配额、话术风格均可按机构定制。

**⑤ 与 rag-ultra 的关系**

- rag-ultra 自身已具备 Milvus partition key 的租户隔离；本系统复用其检索能力时，把 `tenant_id` 透传为 partition key，保证问答知识不跨租户外泄（§12）。

> **业务含义总结**：租户不是「用户分组」那么简单，而是「一个机构在该平台上的完整私有实例」——人、班、知识、题库、配置全部自洽闭环，是权限与隔离的顶层设计单位。

### 9.1 权限控制实现（认证 → 租户隔离 → RBAC → 能力开关 → 资源级 → 审计）

权限控制在本案采用**分层纵深模型**，从「你是谁」到「你能动什么」逐层收敛。各层与代码落点对应如下：

**① 认证（Authentication）— 你是谁**
- 登录走 `POST /api/v1/auth/login`（`user.username` + 明文密码比对），签发 JWT；之后每个请求只带 `Authorization: Bearer`，`backend/middleware/auth.py` 的 `get_current_user` 解 payload 取 `user_id` + `tenant_id`。超管 token 无租户，`tenant_id` 保持 `None`，只按「主租户 + admin」校验身份，**不补主租户、不进业务链路**；租户身份再查 `agent_user_tenant` 得出角色名与 scopes，写入 `request.state` 并贯穿全链路（含 SSE trace）。
- 不提供注册、改密、验证码；JWT 只承载 `user_id`，角色与权限始终查库，不信任 token 内的快照。
- 无合法凭证 → 401；token 与 header 不一致、跨租户访问 → 403。

**② 租户隔离（Tenant Boundary）— 你的数据边界（物理底线）**
- 所有读写强制带 `tenant_id`：PG 行级过滤（`WHERE tenant_id = :tid`）、Milvus partition key、Redis `t:{tenant}:u:{user}:session:{thread}` 前缀（§9）。
- 跨租户访问在存储层即被拦截，是权限的**不可绕过底线**。

**③ 角色与授权（RBAC）— 你能调哪些能力**
- EduAgent 场景角色 4 个（`agent_role.name` 为准，不读 `role_id` 数字）：`student` / `teacher` / `tenant_admin` / `admin`。角色经 `agent_role_permission` 映射到 scopes，scopes 决定可调用的 Agent / 工具 / 端点：
  - `student`：问答、模拟面试、简历审查（仅本人）、查看本人轨迹。
  - `teacher`：上述 + 试卷批改、HITL 审批（`/api/v1/escalations` resume）、查看本班数据。
  - `tenant_admin`：本租户用户与角色（`rbac:*`）、本租户审计（`audit:read`）；**不含** `agent:*` / `model:*` / `config:*` / `tenant:*`。
  - `admin`（仅主租户、全局唯一）：`*`，含租户管理、agent 域、模型配置、配置中心、全量审计。
- 授权在 `backend/security/security.py` 以依赖强制（`require_scope(...)`、`require_super_admin()`、`require_tenant_admin()`），路由注册时声明所需最小权限；Scope 枚举集中在 `backend/security/rbac.py`，拼错在导入期即报错。

**④ 能力 / 插件开关（Capability Gating）— 租户级可用面**
- `AgentRegistry` 与 `PluginRegistry` 支持按租户 enable/disable（§15.1 步骤13 / §15.2 租户开关）：某租户未开通「模拟面试」则 Orchestrator 路由直接拒答，返回明确错误而非越权执行。

**⑤ 资源级权限（Resource-level）— 你只能动自己的**
- 业务资源（简历/答卷/会话）带 `owner_user_id` / `created_user_id` / `class_id`；学生仅访问 own，教师仅本班。在 `models/` 查询层加 ownership 断言，越权返回 403。会话（`agent_thread`）按 `(tenant_id, user_id)` 过滤，`X-Thread-Id` 不匹配归属即 404。

**⑥ 操作权限与防越权（Operation Gating）**
- 高风险动作（HITL 发布、配置变更、能力开关）需 `teacher`/`admin` 且经 `interrupt()` → `resume()` 显式确认，不自动执行（§3.4 / §9）。
- 输入护栏拦截 Prompt 注入（防借注入绕过权限），输出护栏二次过滤防跨租户泄露（§9）。

**⑦ 审计（Auditability）**
- 所有认证失败、越权尝试、特权操作、HITL 决策、能力开关变更写入 `agent_audit_log`（§5.2 / §9），字段为 `tenant_id` / `user_id` / `action` / `target` / `detail` / `create_at`，供追溯与合规（该表当前无 `trace_id` 列，需要链路串联时得先加列）。

**支撑数据模型（已落地）**

| 表 | 用途 |
|---|---|
| `agent_role` / `agent_role_permission` | RBAC 角色—权限点映射 |
| `agent_user_tenant` | 用户—租户—角色分配（PK 保证单租户单角色，跨租户可多角色） |
| `agent_capability_policy` | 租户级 Agent / 插件开通策略 |
| `menu` | 菜单目录 + `scope`，按用户 scopes 过滤后下发（菜单只控入口显隐，不是安全边界） |
| `user` / `tenant` | 登录认证主表与租户边界（`username` 唯一、`tenant.enabled`/`is_primary`） |

> **原则**：认证在边界、隔离在存储、授权在路由、开关在注册表、权属在查询、留痕在审计——六层纵深，任一层失效不导致全局越权。

---

## 10. 工程化（复用团队范式 · 单应用）

复用 `AppServer` + `XXManager` 启动范式，全部模块在同一应用内装配：

```python
server = AppServer("agent-platform")   # 服务启动器：各 XXManager 物理位于 backend/server/managers/
server.register(ConfigManager(),            0)
server.register(LoggingManager(),          10)
server.register(RedisManager(),            20)
server.register(PostgreSQLManager(),       30)   # asyncpg engine
server.register(CheckpointerManager(),     35)   # AsyncPostgresSaver.setup()
server.register(MilvusManager(),           40)
server.register(ModelManager(),            50)   # LLM/bge-m3/bge-reranker/bert-chinese
server.register(MemoryManager(),           55)
server.register(PluginManager(),           60)    # 插件/能力注册与隔离
server.register(RagAdapterManager(),       62)   # rag-ultra 适配层初始化
server.register(OrchestratorManager(),     65)   # 注册四 Agent 图
server.register(ObservabilityManager(),    68)   # Langfuse
server.register(SecurityManager(),         70)
server.register(FastAPIManager(app),     100)
# 单应用：无需 Nacos 服务发现（非多服务）；如需多副本由反向代理/LB 前置
```

- **优雅启停**：按依赖顺序启动；任一项失败 fail-fast；停机逆序释放；uvicorn drained 在途请求。
- **多进程**：gunicorn + 多 uvicorn worker 时，建表/迁移/消费者启动用 Redis 分布式锁保证只跑一次。
- **配置集中**：`ConfigManager` 加载校验 → `app_state.settings`，其余只消费。

---

## 11. 部署与水平扩展（单应用多副本）

```
                   ┌──────── 反向代理 / LB ────────┐
                   │                                │
   客户端 ─▶ LB ──▶ agent-platform 副本1 (无状态)
                 ├─ agent-platform 副本2 (无状态)   ← 增删副本无需迁移
                 └─ agent-platform 副本N
                          │
   ┌──────────────────────┼──────────────────────────────┐
   │ PostgreSQL（状态真相源）│ Redis        │ Milvus       │
   │ checkpointer+业务+记忆 │ 会话/缓存/队列│ 向量(BGE-M3)  │
   └──────────────────────┘               └──────────────┘
```

- **无状态运行时**：应用不持有会话状态，状态全在 PG/Milvus/Redis → 副本数随负载上调，无会话粘连。
- **外置状态**：LangGraph `AsyncPostgresSaver` 持久化 checkpoints；任意副本可接管任意 thread。
- **RAG 外置**：rag-ultra 独立部署/导入，本系统通过适配层调用，检索压力不压在主应用。
- **多租户**：partition key + Redis 前缀 + PG 行级隔离三件套。

---

## 12. 与 rag-ultra 的边界（不重复造轮子）

| 能力 | 归属 | 本系统动作 |
|---|---|---|
| 文档读取 / 智能分块 / BGE-M3 嵌入 / Milvus 写入 | **rag-ultra** | 直接复用，本系统调用其索引接口 |
| Hybrid 召回（WeightedRanker）/ bge-reranker-v2-m3 精排 | **rag-ultra** | 通过 `backend/rag` 适配层暴露为 `rag_retrieve` 工具 |
| 问答图编排 / 意图分类 / 记忆 / SSE / HITL | **本系统** | 自己实现（LangGraph + bert-chinese + memory） |
| 简历/批改/面试 Agent | **本系统** | 自己实现（与 RAG 解耦，仅按需调用 `rag_retrieve`） |

> 设计原则：**检索是平台的一种能力，由 rag-ultra 提供；Agent 编排是另一种（更上层的）能力，由本系统提供**。两者通过适配层解耦，未来替换检索底座不影响 Agent 逻辑。

---

## 13. 里程碑 / Roadmap

| 阶段 | 目标 | 关键交付 |
|---|---|---|
| M0 | 脚手架 | 单应用 `backend/` 骨架（core/agents/api/rag/plugins）+ AppServer/Manager 接入 |
| M1 | 工程地基 | ConfigManager、LLM Factory（含 bge-m3/bge-reranker-v2-m3/bert-chinese）、PostgreSQL/Milvus/Redis Manager、认证 |
| M2 | 编排核心 | Orchestrator + AgentRegistry + AsyncPostgresSaver 状态外置；四 Agent 图骨架 |
| M3 | 简历 Agent | PDF 解析→六维度并行→诊断→持久化（bert-chinese 维度标注） |
| M4 | RAG 适配 | `backend/rag` 接入 rag-ultra；qa Agent 图（分类/HyDE/多查询/检索/精排/生成/记忆） |
| M5 | 试卷批改 Agent | Word 解析→三轨并行→汇总→HITL→教师确认发布 |
| M6 | 模拟面试 Agent | 状态机→SSE 多轮→质量评估→报告→记忆 |
| M7 | 统一入口 | unified_chat：前置拦截（bert-chinese）+ LLM 路由 + SSE 分发；单 Agent / 多 Agent Pipeline |
| M8 | 插件化 | PluginRegistry/协议/隔离；web_search / code_exec 等能力插件 |
| M9 | 可观测与安全 | Langfuse 轨迹 + Prometheus；输入/输出护栏 + 审计 |
| M10 | 部署扩展 | 单应用多副本、外置状态、租户隔离加固、长任务 worker |

---

## 14. 参考项目与方法论借鉴（映射参考源码清单）

| 参考项目 | 学什么 | 本方案落点 |
|---|---|---|
| **langchain-ai/langgraph** | 图编排、supervisor/worker、checkpointer 持久化 PG | 四 Agent 图 + `AsyncPostgresSaver`（§3） |
| **TencentCloud/octop-harness** | deepagents + LangGraph 工程化为生产级（隔离/HITL/会话压缩） | 单应用内 Agent 隔离、HITL（§3.4）、会话压缩 |
| **langgenius/dify** | 企业级平台壳（多租户/RBAC/工作流） | 多租户/RBAC/分层范式（§9） |
| **deepseek-ai/deepseek-harness**（Cordis） | 一切皆插件、append-only tracing | 插件协议（§8）、`agent_messages` 不可变轨迹 |
| **letta-ai/letta** | PostgreSQL 持久记忆 + 内存分页 | 长期记忆（§6.1） |
| **run-lama/llama_index** | RAG 管线（混合检索 + rerank） | 经 rag-ultra 复用，不重建（§6.2/§12） |
| **milvus-io/milvus** | 向量库本体、partition 租户隔离 | **主向量库**（§5.1，无 PGVector 过渡） |
| **langfuse/langfuse** | 开源 LLM 轨迹追踪、token/成本/复盘 | 可观测层（§10） |
| **postgres/postgres** | LangGraph 状态 + 业务/审计存储 | 状态真相源（§5） |
| **EduAgent 官方文档** | 四大 Agent 业务范式、Orchestrator、统一入口 SSE | 业务蓝本与模块划分（§0.1/§2.1/§7） |
| **rag-ultra（既有）** | RAG 检索/索引/精排实现 | 直接复用，仅做适配层（§6.2/§12） |

### 14.1 关键结论（沿用参考清单 + 本次约束）

- **心在 LangGraph + octop-harness**：编排内核用 LangGraph，工程化封装对齐 octop-harness（不直接 fork Octop 主仓）。
- **平台骨架抄 Dify**：多租户/RBAC/分层范式借鉴，运行时自控。
- **向量库用 Milvus**（本次约束）：BGE-M3 + Hybrid(WeightedRanker) + bge-reranker-v2-m3，不再以 PGVector 过渡。
- **模型四件套**（本次约束）：bge-m3（嵌入）、bge-reranker-v2-m3（重排）、bert-chinese（中文意图/分类快路径）、LLM（生成+复杂路由）。
- **RAG 复用 rag-ultra**（本次约束）：不重写检索管线，仅做集成适配层。
- **多模块单应用**（本次约束）：不拆多服务，模块内聚、进程内协作，仍可由 LB 前置做多副本水平扩展。

---

## 15. 扩展指南：新增 Agent 流程 与 可插件化能力清单

### 15.1 今后新增一个 Agent 需要做什么

本方案的可扩展性收益在于：**新增 Agent = 新增一个包 + 注册 + 路由标签（+ 可选模型/端点/表），不改动 Orchestrator 核心与其他 Agent**。标准动作（以新增「作业辅导 Agent」为例）：

| 步骤 | 动作 | 落点 |
|---|---|---|
| 1 业务建模 | 确定流程形状（并行 fan-out/fan-in / 状态机+HITL / RAG / 三轨）与核心节点 | 设计阶段 |
| 2 建包 | `backend/agents/<new>/` 下建 `state.py`(TypedDict) / `nodes.py` / `graph.py`(`build_<new>_graph`：StateGraph+Checkpointer+条件边) / `api.py` | `backend/agents/<new>/` |
| 3 继承基类 | 继承 `backend/agents/base.py` 的 `Agent`，实现 `build_graph()` / `input_schema()` / `metadata()`；模块加载时 `AgentRegistry.register(agent_type, build_graph, schema)` | `base.py` + 包 `__init__` |
| 4 意图路由 | 给 bert-chinese 增加新意图标签（如 `homework`）；在 `unified_chat.py` 增加「标签→Agent」映射与 SSE 事件；模糊意图仍走 LLM 兜底自动识别 | `core/llm_factory`、`api/v1/unified_chat` |
| 5 编排接入 | 单 Agent 直达：Orchestrator 按 `agent_type` 取图执行；若需串联，pipeline 加节点、前置输出作后置输入（State 透传字段） | `core/orchestrator` |
| 6 数据模型 | `backend/models/business/` 增该 Agent 元数据表；HITL 复用 `agent_escalations` | `models/business/` |
| 7 API 端点 | `backend/api/v1/agent/<new>.py` 暴露直连接口；统一入口已自动覆盖（路由命中即可） | `api/v1/agent/` |
| 8 记忆(可选) | 复用 `core/memory.py` 短期/长期/语义接口，无需自建 | `core/memory` |
| 9 工具/能力 | 通用工具做 `backend/plugins/builtin/<tool>/`（含 `manifest.yaml` + `AgentPlugin`）；专属逻辑留本包内 | `plugins/` |
| 10 配置 | `backend/config/schemas.py` 增该 Agent 专属项（模型/阈值/开关），经 ConfigManager 加载 | `config/` |
| 11 安全可观测 | 沿用 `tracing.py`(Langfuse) / `security.py` 护栏 / audit 写入；HITL 走 `interrupt()` / `resume()` | `core/` |
| 12 测试 | `tests/agents/<new>/` 对等单测 + 图集成测试 + 意图路由测试 | `tests/` |
| 13 开关 | `AgentRegistry` 支持 enable/disable（租户级能力开关），无需改核心 | `core/agent_registry` |

> **关键约束**：Orchestrator 调度、`StateGraph` 编译、Checkpointer 持久化、ConfigManager、AppServer 启动器、认证/租户隔离骨架、SSE 事件协议属**平台内核**，新增 Agent 只在其上挂接，内核保持稳定可预测（呼应「受控工作流」设计哲学）。

### 15.2 插件设计：哪些功能可以插件化

插件（capability seam）面向「工具/能力」，由 `protocol.py`(`AgentPlugin`) + `registry.py` + `loader.py` + `builtin/` + `external/` 支撑，具备**协议驱动、错误边界隔离、版本/依赖清单、扫描发现、生命周期管理、租户开关**六大特性。

**可插件化的能力类别（建议）**：

| 类别 | 示例插件 | 说明 |
|---|---|---|
| 检索/知识源 | `rag_retrieve`(已建)、`web_search`、`faq_retriever`、`doc_lib_retriever`、`db_query` | 不同知识源 / 向量库的检索接入 |
| 工具/执行器 | `pdf_parse`、`word_parse`、`code_exec`(规划)、`excel_parse`、`image_ocr`、`calculator`、`sql_exec` | 具体动作执行 |
| 模型适配器 | LLM 供应商(OpenAI/DeepSeek/本地 vLLM)、embedding 备选、reranker 备选、分类器备选 | 模型后端可插拔 |
| 评估/打分器 | 简历维度评分器、客观题判分规则、面试质量评估器、通用 rubric | 评分逻辑可 A/B 与替换 |
| 输出格式化 | Markdown/卡片/表格渲染、报告生成(PDF/Word)、SSE 事件包装 | 渲染策略可换 |
| 护栏/安全 | 输入违禁词 DFA、Prompt 注入检测、输出泄露过滤、外部审核 | 多 guardrail 串成链 |
| 记忆后端 | 长期记忆存储(PG/向量/外部 KMS)、记忆压缩策略 | 记忆落点可插拔 |
| 通知/动作通道 | 邮件、企业微信/飞书、Webhook、工单系统 | HITL 确认后外发动作 |
| 路由策略 | bert-chinese-router / LLM-router / 规则-router / 混合-router | 意图分类器可替换 |
| 可观测 Sink | Langfuse / Prometheus / 自定义日志 | 埋点出口可插拔 |

**应保持内核、不插件化的**：Orchestrator 调度、`StateGraph` 编译、Checkpointer 持久化、ConfigManager、AppServer 启动器、认证/租户隔离骨架、SSE 事件协议。

> **设计收益**：新增能力 = 新增 `backend/plugins/builtin/<cap>/`（含 `manifest.yaml` 声明 name/version/capabilities/dependencies），`PluginManager` 启动时扫描注册；外部生态经 `external/`（entry-points）注入。**单能力故障不影响整体**（错误边界 + 超时 + 熔断），并支持租户级启用/禁用与灰度回滚。

### 15.3 场景化可插件化清单（EduAgent 四大 Agent）

> 在「多模块单应用」前提下，四大 Agent 的具体能力中，凡具备「可独立替换、可 A/B、可租户级开关、可外部注入」特征的，都应抽成插件挂接于 `backend/plugins/`，**而非写死在 Agent 包内**。

**15.3.1 按 Agent 拆解**

| 所属 Agent | 可插件化能力 | 插件示例 | 替换 / 扩展场景 |
|---|---|---|---|
| 简历审查 | 文档解析 | `pdf_parse`（已规划）、`resume_ocr` | 换 PDF 库 / 加图片 OCR 简历 |
| 简历审查 | 维度评分器（六维度） | `resume_scorer_content` `resume_scorer_structure` `resume_scorer_match` … | 每维度独立评分逻辑可 A/B、换权重/模型 |
| 简历审查 | 岗位/人才库匹配检索 | `talent_retriever` | 对接不同人才库 / 向量库 |
| 简历审查 | 报告渲染 | `resume_report_pdf` `resume_report_html` | 不同输出格式 |
| 智能问答 | 知识检索 | `rag_retrieve`（已建，接 rag-ultra）、`faq_retriever`、`doc_lib_retriever` | 接不同知识源 / FAQ 精确匹配 |
| 智能问答 | 低置信兜底 | `web_search`（已规划） | 联网兜底可换搜索引擎 |
| 智能问答 | 查询改写 / HyDE | `query_rewriter` | 改写策略可插拔 |
| 智能问答 | 答案渲染 | `qa_renderer_md` `qa_renderer_card` | 不同前端形态 |
| 试卷批改 | 试卷解析 | `word_parse`（已规划）、`exam_pdf_parse` | 不同试卷格式 |
| 试卷批改 | 客观题判分规则 | `objective_grader` | 按学科 / 题型换规则引擎 |
| 试卷批改 | 主观题 rubric | `subjective_rubric` | 评分尺度可 A/B |
| 试卷批改 | 代码题沙箱 | `code_exec`（规划） | 不同沙箱 / 语言运行时 |
| 试卷批改 | 查重 / 雷同检测 | `plagiarism_check` | 外部查重服务 |
| 模拟面试 | 题库检索 | `interview_bank_retriever` | 不同题库源 |
| 模拟面试 | 回答质量评估 | `interview_evaluator` | 评估 rubric 可换 |
| 模拟面试 | 面试官人设 / 风格 | `interviewer_persona` | 不同岗位语气 / 风格 |
| 模拟面试 | 报告渲染 | `interview_report_pdf` | 面试报告格式 |

**15.3.2 跨 Agent 的公共插件（基础设施层）**

| 类别 | 插件示例 | 说明 |
|---|---|---|
| 模型适配器 | LLM 供应商(OpenAI/DeepSeek/本地 vLLM)、`bge-m3` embedding 备选、reranker 备选、bert-chinese 分类器备选 | 四大 Agent 共用，后端可插拔 |
| 路由策略 | `bert_chinese_router` / `llm_router` / `rule_router`（混合） | 意图分类器可替换 |
| 护栏 / 安全 | 输入注入检测、输出泄露过滤、内容审核 | 多 guardrail 串链，全 Agent 复用 |
| 记忆后端 | 长期记忆存储(PG/向量/外部 KMS)、记忆压缩策略 | 问答 / 面试的记忆可换落点 |
| 通知 / 动作 | 邮件、企业微信/飞书、Webhook、工单 | HITL（批改/面试）确认后外发 |
| 可观测 Sink | Langfuse / Prometheus / 自定义日志 | 埋点出口可插拔 |

> **原则**：插件只承载「能力 / 工具」，**编排、`StateGraph`、Checkpointer、HITL 机制、SSE 协议、认证/租户隔离保持内核**。新增一种检索源 / 评分器 / 渲染格式 = 新增一个插件包，四大 Agent 通过 `AgentRegistry` 消费，互不侵入。

---

## 附录 A · 建议目录结构（多模块单应用 · 项目名 agent-platform）

> 运行环境：conda `agent_platform`（Python 3.12）。项目根目录 `agent-platform/`，应用包为 `backend/`（import 命名空间 `backend.*`）；`EduAgent` 仅指业务蓝本，非代码包名。

```
agent-platform/                              # 项目根（git repo）
├─ pyproject.toml                            # 包元数据 + 依赖（conda: agent_platform, py3.12）
├─ README.md
├─ .env.example                              # DB / Milvus / Redis / 模型网关 / Langfuse 配置样例
├─ docker-compose.yml                        # 本地一站起（postgres / milvus / redis）
├─ Makefile                                  # install / dev / format / test 常用命令
├─ deploy/
│  ├─ Dockerfile                             # 多阶段构建（基于 conda agent_platform 镜像）
│  └─ gunicorn.conf.py                       # 多 uvicorn worker（配合 Redis 分布式锁）
├─ backend/                                  # 应用包（import: backend.*）
│  ├─ main.py                                # 入口：装配 routers + AppServer().run()
│  ├─ app_state.py                           # 全局 settings / 共享资源单例
│  ├─ config/                                # 配置（ConfigManager）
│  │  ├─ settings.py                         # ConfigManager：env/YAML + Pydantic 校验 → app_state.settings
│  │  └─ schemas.py                          # 配置 schema 定义
│  ├─ server/                                # 【服务启动器】AppServer + 各 XXManager
│  │  ├─ app_server.py                       # AppServer：register(manager, order) + 单一 run()
│  │  ├─ base_manager.py                     # Manager 抽象基类（start / stop / health）
│  │  ├─ register.py                         # 集中注册（order=0~100，见 §10）
│  │  └─ managers/
│  │     ├─ logging_manager.py
│  │     ├─ redis_manager.py
│  │     ├─ postgres_manager.py              # asyncpg engine
│  │     ├─ checkpointer_manager.py          # AsyncPostgresSaver.setup()
│  │     ├─ milvus_manager.py
│  │     ├─ model_manager.py                 # LLM / bge-m3 / bge-reranker / bert-chinese
│  │     ├─ memory_manager.py
│  │     ├─ plugin_manager.py                # 【插件管理】启动扫描 / 注册 / 隔离 / 启停
│  │     ├─ rag_adapter_manager.py           # rag-ultra 适配层初始化
│  │     ├─ orchestrator_manager.py          # 注册四 Agent 图
│  │     ├─ observability_manager.py         # Langfuse / Prometheus
│  │     ├─ security_manager.py
│  │     └─ fastapi_manager.py               # 挂载 routers + SSE
│  ├─ core/                                  # 编排运行时内核
│  │  ├─ orchestrator.py                     # 编排器（单Agent直达 / 多Agent串联）
│  │  ├─ agent_registry.py                   # Agent/能力注册与发现
│  │  ├─ llm_factory.py                      # LLM 工厂（三层兜底+重试）
│  │  ├─ memory.py                           # 短期/长期/语义记忆抽象
│  │  ├─ security.py                         # 护栏 / 认证依赖 get_current_user
│  │  ├─ exception.py                        # 异常体系 + 三层兜底
│  │  └─ tracing.py                          # Langfuse trace 封装
│  ├─ agents/                                # 四业务 Agent（每 Agent 一个子包）
│  │  ├─ base.py                             # Agent 基类（build_graph / schema / register）
│  │  ├─ resume/    (state.py / nodes.py / graph.py / api.py)
│  │  ├─ qa/        (state.py / nodes.py / graph.py / api.py)
│  │  ├─ exam/      (state.py / nodes.py / graph.py / api.py)
│  │  └─ interview/ (state.py / nodes.py / graph.py / api.py)
│  ├─ rag/                                   # rag-ultra 集成适配层（不重建）
│  │  ├─ adapter.py                          # rag_retrieve(query, tenant_id, top_k) -> List[Chunk]
│  │  └─ client.py                           # 包导入 / HTTP 接入 RAG-Ultra
│  ├─ plugins/                               # 【插件管理】能力缝隙
│  │  ├─ protocol.py                         # AgentPlugin 协议（name/version/capabilities/register/get_tools/health）
│  │  ├─ registry.py                         # 运行时插件注册表（与 AgentRegistry 联动）
│  │  ├─ loader.py                           # 扫描 backend/plugins + entry-points
│  │  ├─ builtin/                            # 内置插件（每插件独立子包 + manifest.yaml）
│  │  │  ├─ web_search/  (__init__.py / tool.py / manifest.yaml)   # 联网兜底
│  │  │  └─ code_exec/   (__init__.py / tool.py / manifest.yaml)    # 代码题沙箱（规划）
│  │  └─ external/                           # 外部插件挂载点（entry-points 注入）
│  ├─ data/                                  # 数据层
│  │  ├─ postgres/                           # 表结构模型（仅供 gen_schema.py 生成 DDL，运行期不加载）
│  │  │  ├─ base.py
│  │  │  ├─ threads.py / runs.py / messages.py  # 会话 / 运行台账 / append-only 轨迹
│  │  │  ├─ plugins.py / tools.py / escalations.py
│  │  │  ├─ memory.py / audit.py
│  │  │  └─ business/                        # 简历/问答/批改/面试元数据表
│  │  ├─ sql/                                # 运行时数据访问：session_scope / fetch_* / 审计列注入
│  │  └─ dao/                                # DAO：SQL 全部 text() 手写，返回 dict
│  ├─ middleware/                            # 接入层中间件
│  │  ├─ auth.py                             # get_current_user 依赖注入
│  │  ├─ trace_id.py                         # 全链路 trace_id 注入
│  │  └─ rate_limit.py                       # 租户级限流
│  └─ api/
│     └─ v1/
│        ├─ unified_chat.py                  # 统一入口（前置拦截+路由+SSE）
│        ├─ resume.py / qa.py / exam.py / interview.py   # 各 Agent 直连
│        ├─ orchestrator.py                  # pipeline 运行端点
│        ├─ threads.py                       # 会话状态 / HITL resume
│        ├─ plugins.py                       # 已注册能力清单
│        └─ escalations.py                   # 人工队列（控制台）
├─ tests/                                    # 单测 / 集成 / e2e（各模块对等目录）
└─ docs/                                     # 设计文档 / ADR
```

## 附录 B · 关键接口草图

```python
# 统一入口（SSE）
POST /api/v1/chat            # 一句话 → 前置拦截 → bert-chinese/LLM 路由 → SSE 分发
# 各 Agent 直连
POST /api/v1/resume/...      # 简历审查
POST /api/v1/qa/...          # 智能问答（内部走 rag_retrieve）
POST /api/v1/exam/...        # 试卷批改（HITL）
POST /api/v1/interview/...   # 模拟面试（SSE 多轮）
# 编排与运维
POST /api/v1/orchestrator/run        # 指定 agent_type 或 pipeline_plan
GET  /api/v1/threads/{id}            # 取会话状态
POST /api/v1/threads/{id}/resume     # HITL 注入决策后继续
GET  /api/v1/admin/agents            # 已注册 Agent/能力清单（超管，按 tenant 过滤）
GET  /api/v1/escalations             # 人工队列（控制台）
```
