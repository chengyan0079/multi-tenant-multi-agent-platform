# 多租户多智能体协作平台

单仓三块：`backend/` 一个 FastAPI 应用、`dashboard/` 管理后台前端（React + Ant Design）、`offline/` 意图模型离线训练与评估。

本文件按**当前代码实况**维护：已跑通的写在前面，骨架、占位、未接入项集中标注，不把“代码存在”写成“能力可用”。设计与表结构见 `docs/`。

> 文档基线：2026-11-06。最近一轮同步覆盖了 QA/简历/考试、消息队列、审计、看板、Prompt Nacos、租户能力策略等实现。

## 1. 现在能跑什么

| 能力 | 入口 | 说明 |
| --- | --- | --- |
| 登录与身份 | `POST /api/v1/auth/login`、`GET /auth/me`、`GET /auth/menus` | 密码校验（bcrypt），签发 JWT；成功/失败都落 `agent_login_log`；菜单按 scopes 从库下发 |
| 认权 | 路由装配处统一挂依赖 | JWT 验签后查 RBAC 表得 `scopes`；`admin/**` 整组超管，`tenant/**` 整组租户上下文 |
| 监控看板 | `GET /api/v1/dashboard` | 超管看全局/聚焦租户，租户管理员只看本租户；60 秒缓存，支持 `refresh=true` |
| 管理后台 API | `/api/v1/admin/**` | 租户、用户/角色/菜单、Agent 定义与开通策略、插件、模型、消息、审计、配置中心 |
| 租户业务 API | `/api/v1/tenant/**` | QA、简历、考试、文件、消息、审计、用户/角色、编排入口 |
| QA 知识问答 | `/tenant/qa/chat/stream`、`/chat/stop`、`/qa/sessions`、`/qa/results` | SSE 流式问答、停止生成、会话/历史、结果/RAGAS 质量评估；Prompt 走 Nacos |
| 简历评审 | `/tenant/resume/upload`、`/reviews` | PDF 上传 → Outbox `resume.review` → LangGraph 六维评审 → 报告详情；Prompt 走 Nacos |
| 考试批改 | `/tenant/exam/submit`、`/submissions/{id}/review`、`/confirm` | Word 提交 → 三轨批改 → 汇总/薄弱点 → `interrupt()` 教师复核 → 确认发布；Prompt 走 Nacos |
| 模拟面试 | `/tenant/interview/sessions`、`/chat/stream`、`/report` | 建会话并生成开场白 → 多阶段 SSE 面试 → 自动报告；Prompt 走 Nacos |
| 文件知识库 | `/tenant/agent/files/**` | MinIO 上传/下载、批量上传、解析入 Milvus；已解析/解析中不会重复提交 |
| 消息管理 | `/api/v1/admin/messages/**`、`/tenant/messages/**` | Outbox 队列、死信队列、重投/完成/失败；失败态保留错误原因 |
| 审计 | `/admin/audit/logs`、`login-logs`、`api-logs` | 业务审计、登录日志、API 调用日志；租户/用户 ID 已 JOIN 成名称，支持租户与调用域筛选 |
| 配置中心 | `/api/v1/admin/config/**` | 配置查询/历史、申请/复核/撤回；通过后写 Nacos |
| 模型注册表 | `/api/v1/admin/models/**` | llm/embedding/reranker/classifier 的 active 记录驱动运行时，api_key 出参脱敏 |
| Nacos | `NacosConfigManager`、`NacosDiscoverManager`、`NacosAIManager` | 配置中心、服务发现、MCP Server 发布；Prompt 读取 `group=PROMPT` |
| 日志 | `backend/common/logger.py` | loguru 双写；启动/后台日志不带 trace，HTTP 请求内才注入 trace |
| 管理后台前端 | `dashboard/` | 登录、看板、Agent/工具/模型、RBAC、配置中心、审计、消息、QA/简历/面试页面；考试页仍为 mock |

## 2. 未实现 / 已知限制

| 项 | 现状 |
| --- | --- |
| 面试会话删除 | 当前为软删归档：`agent_interview_sessions.status=deleted` + `agent_thread.status=archived`；checkpointer 状态保留可恢复，未做物理清理 |
| 考试前端 | 后端提交/复核/确认接口与考试图已就绪，但 `dashboard/src/pages/agent/exam/*` 仍是 mock 数据，需要继续对接 |
| `agent_run` 运行台账 | 表已建、字段齐全（prompt/completion tokens、cost、延迟），但当前没有写入链路；Token 总消耗暂时查不到 |
| 看板业务口径 | `agent_run` 为空时，成功率/调用占比用 API 日志兜底；智能体数按「全局启用且未被租户显式关闭」计算 |
| 业务审计覆盖 | `agent_audit_log` 目前主要记录 RBAC/租户/配置等管理动作；QA/简历/文件等业务操作没有逐条写业务审计，看板会用最近 API 调用兜底 |
| 统一入口 | 旧 `chat/unified` 已下线；目前各 Agent 走独立入口，没有统一意图路由 |
| 工具调用统计 | 插件页只有能力清单/启停，没有调用次数统计 |
| 长期记忆 | 已注册 MemoryManager，但记忆读写链路仍未全面接入业务 |
| Observability | `ObservabilityManager` 仍未注册，Langfuse/tracing 只有占位 |
| 离线任务 | `offline/tasks/review`、`agent_audit` 仍抛 `NotImplementedError` |
| Broker | `BrokerManager` 受 `RABBITMQ_ENABLED` 控制；未启用时 Outbox 只缓冲不投递 |
| 租户能力策略 | `agent_capability_policy` 是租户级开关；**未配置视为开通**，只有 `enabled=false` 才关闭 |

## 3. 架构与装配现状

```
Browser / curl
      │  Authorization: Bearer <JWT> + X-Trace-Id
      ▼
FastAPI  backend/api/router.py → /api/v1
   ├── admin/**   整组 require_super_admin
   ├── tenant/**  整组 require_tenant（超管 403）
   ├── auth/**    /login 公开，/menus /me 挂 get_current_user
   └── health、dashboard
      │
      ├── middleware：trace_id（纯 ASGI，兼容 SSE）→ api_log（落库）→ 限流
      ├── security：JWT → RBAC 查库 → scopes → require_scope
      ▼
Orchestrator ── AgentRegistry（已装配，从 agent / capability_policy 加载）
      ├── QA：分类/HyDE/Multi-Query/检索/生成/记忆（checkpointer）
      ├── Resume：解析→结构化→六维→问题→总结→回写（线性，不绑 checkpointer）
      ├── Exam：解析→三轨→汇总→薄弱点→教师复核（interrupt，checkpointer）
      └── Interview：多阶段状态机 → SSE 生成 → 报告回写（checkpointer）
      ▼
PostgreSQL / Redis / Milvus / MinIO / RabbitMQ / Nacos
```

启动顺序（`backend/server/register.py`，同 order 并行、跨 order 串行，失败回滚）：

| order | 组件 |
| --- | --- |
| 10 | Logging |
| 20 | Redis、PostgreSQL、Model、Security；Broker（受开关控制） |
| 30 | Scheduler、Plugin、Milvus、Checkpointer、Memory |
| 40 | Orchestrator |
| 50 | FastAPI |
| 60 | Nacos 配置中心 |
| 70 | Nacos 服务发现 |
| 75 | Nacos AI（MCP Server 发布） |

`ObservabilityManager` 仍未注册。

## 4. 目录结构

```
backend/
├─ main.py                 入口：AppServer 装配 + uvicorn
├─ app_state.py            进程级单例 + 请求上下文 contextvars
├─ server/                 AppServer / BaseManager / register.py / managers/*
├─ config/                 pydantic-settings 读 .env → config 单例
├─ api/
│  ├─ router.py            按 admin / tenant / auth / 系统域分组挂载
│  └─ v1/{admin,tenant,auth}/、dashboard.py、health.py
├─ agents/{qa,resume,exam,interview}/   state + graph + nodes + prompts
├─ orchestration/          Orchestrator + AgentRegistry
├─ broker/                 Outbox / publisher / consumer / handlers / 定时任务
├─ mcp/                    protocol / registry / builtin / retrieval / external
├─ common/                 四模型工厂 / memory / config_center / logger / response
├─ security/               rbac / security（JWT、依赖、输入护栏）
├─ middleware/             auth / trace_id / api_log / rate_limit
├─ observability/          exception / tracing（占位）
└─ data/                   clients / dao / postgres（仅生成 DDL）/ sql / milvus
dashboard/                  Vite + React + Ant Design 管理后台
offline/                    离线训练/评估，不 import backend
scripts/                    schema.sql / gen_schema.py / migrations / dev
tests/                      pytest
deploy/                     Dockerfile + gunicorn.conf.py
docs/                       架构、数据库、登录权限、前端对接清单等
```

## 5. 技术栈

- 后端：Python 3.12、FastAPI、pydantic-settings、SQLAlchemy(asyncpg) 手写 SQL、LangGraph/LangChain、sse-starlette、slowapi、loguru、nacos-sdk-python
- 存储：PostgreSQL（业务/权限/审计/checkpoint）、Redis（缓存/短期记忆/停止标记）、Milvus（RAG 文档向量）、MinIO（文件与简历 PDF）、RabbitMQ（Outbox 投递）
- 模型：LLM 走 OpenAI 兼容接口；embedding/reranker/classifier 为 bge-m3、bge-reranker-v2-m3、bert-base-chinese
- 前端：React 18、TypeScript、Ant Design 5、Recharts、Vite 5
- 质量：pytest、ruff

数据访问约定：运行时**不用 ORM**，DAO 全部 `text()` 手写 SQL；`data/postgres` 下的模型只供 `scripts/gen_schema.py` 生成 `schema.sql`。

## 6. 快速开始

```bash
# 1) 依赖
conda create -n agent_platform python=3.12 -y && conda activate agent_platform
pip install -e ".[dev]"

# 2) 配置
cp .env.example .env        # 至少填 JWT_SECRET、POSTGRES_*、NACOS_*

# 3) 中间件（PostgreSQL / Redis / Milvus + etcd / MinIO / RabbitMQ）
docker compose up -d

# 4) 建库与种子
psql -h localhost -U agent -d agent_platform -f scripts/schema.sql
# schema.sql 由 python scripts/gen_schema.py 从模型生成，改表结构后重新生成

# 5) 启动后端（端口取 .env 的 PORT）
python backend/main.py

# 6) 启动前端（另开终端）
cd dashboard && npm install && npm run dev
```

- 后端默认 `PORT=8000`；本仓库 `.env` 现为 `9800`，`dashboard/vite.config.ts` 代理也指向 `9800`。
- 前端固定 `5173`，只代理 `/api` 与 `/v1`；生产需同域反代或 CORS。
- 启动会做模型就绪自检：`agent_model_registry` 中 llm / embedding / reranker / classifier 各需至少一条 `enabled=true`。
- 种子账号：`admin / 123456`（超管，无租户）。
- Nacos 未启动时把 `NACOS_ENABLED`、`NACOS_CONFIG_ENABLED` 置 False；Prompt 会回退代码内置默认值。
- Broker 默认受 `RABBITMQ_ENABLED` 控制；当前示例 `.env` 为 True。

## 7. 配置

统一由 `backend/config/schemas.py`（pydantic-settings）读 `.env`，按分组加前缀；其余模块只消费 `config` 单例。

| 分组 | 前缀 | 关键项 |
| --- | --- | --- |
| 服务 | `SERVICE_*` / `PORT` / `VERSION` | `SERVICE_IP`、`PORT`、`DOCS_ENABLED` |
| PostgreSQL | `POSTGRES_` | host / port / user / password / db / search_path |
| Redis | `REDIS_` | host / port / password |
| Milvus | `MILVUS_` | host / port / db_name / collection |
| RAG 分块/检索 | `QA_` | `PARENT_CHUNK_*` / `CHILD_CHUNK_*` / `RECALL_TOP_K` / `RERANK_TOP_K` / `MAX_UPLOAD_MB` / `AUTO_PARSE` |
| MinIO | `MINIO_` | endpoint / bucket / access_key / secret_key |
| 安全 | `JWT_` | secret / algorithm / expire_minutes |
| 可观测 | `LANGFUSE_` | host 与密钥（tracing 尚未接） |
| Nacos 发现 | `NACOS_` | enabled / server_addr / namespace / group |
| Nacos 配置 | `NACOS_CONFIG_` | enabled / server_addr / namespace / group |
| 日志 | `LOG_*` | level / file / size / file_days |
| API 日志 | `API_LOG_*` | enabled / db / save_body / max_body / exclude |
| 定时任务 | `SCHEDULER_` | `RESUME_TIMEOUT_MIN` / `SCAN_INTERVAL` / `ESCALATION_TIMEOUT_MIN` |
| 离线 | `OFFLINE_*` | data / base_model / model_out / epochs / batch / lr / max_len |

Prompt 支持 Nacos：`group=PROMPT`，`data_id` 为 `qa_*` / `resume_*` / `exam_*` / `interview_*` 小写；Nacos 缺失时回退代码内置默认值。面试字典型提示词兼容 JSON 与 Python 字典字面量。

## 8. API 概览

全部在 `/api/v1` 下。返回统一信封 `{code, msg, data}`；业务失败是 HTTP 200 + `code != 0`，鉴权失败是 401/403。

**认证** `/auth`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/login` | body `{username, password, tenant_id?}` |
| GET | `/me` | 当前身份（用户、租户、角色、scopes） |
| GET | `/menus` | 按 scopes 过滤的菜单树 |
| POST | `/logout` | 失效当前 token 的 Redis 会话 |

**管理域** `/admin`（整组 super_admin）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/agents` | 列表（含租户开通状态）/ 新增 |
| GET/PUT/DELETE | `/agents/{type}` | 详情 / 更新 / 删除 |
| PATCH | `/agents/{type}/enabled` | 全局启停 |
| GET/PUT | `/agents/tenants/{id}/capabilities` | 租户级开通策略 |
| GET/POST/PUT/DELETE | `/agents/{type}/models` | Agent 模型绑定 |
| GET/POST/PUT/DELETE/PATCH | `/models` | 模型注册表 CRUD / 启停 |
| GET/POST/PATCH/DELETE | `/tenants` | 租户列表/新建/启停/删除 |
| GET/POST/PUT/DELETE | `/menus` | 菜单管理 |
| GET/POST/PUT/DELETE | `/roles` | 角色与权限点 |
| GET/PUT | `/rbac/users`、`/rbac/roles` | 用户/角色管理 |
| GET/POST/PATCH | `/plugins` | 插件清单/新增/启停 |
| GET/POST/PUT/DELETE | `/config/*` | 配置查询、申请、复核、撤回 |
| GET | `/audit/logs`、`/audit/login-logs`、`/audit/api-logs` | 业务审计 / 登录日志 / API 调用日志 |
| GET/PATCH | `/messages/queue`、`/messages/dead-letters` | 消息队列 / 死信队列 / 状态变更 |

**租户域** `/tenant`（整组需租户 token，超管 403）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/qa/chat`、`/qa/chat/stream`、`/qa/chat/stop` | 普通/流式问答、停止生成 |
| GET/POST/DELETE | `/qa/sessions` | 会话列表/新增/删除/详情 |
| GET | `/qa/results`、`/qa/results/{id}`、`/quality` | 问答结果、详情、RAGAS 质量 |
| POST | `/qa/results/{id}/review` | 触发 RAGAS 测评 |
| POST | `/resume/upload` | 上传 PDF，异步评审 |
| GET/DELETE | `/resume/reviews`、`/reviews/{id}` | 评审列表/详情/删除 |
| POST | `/exam/submit` | 提交试卷，异步批改 |
| GET | `/exam/my-submissions`、`/submissions/{id}/review` | 我的提交、教师复核 |
| POST | `/exam/submissions/{id}/confirm` | 教师确认并发布 |
| POST | `/interview/sessions` | 创建面试会话并生成开场白 |
| POST | `/interview/sessions/{id}/chat`、`/chat/stream` | 普通/流式多轮面试 |
| POST | `/interview/chat/stop` | 写 Redis 停止标记，停止当前流式生成 |
| GET | `/interview/sessions` | 面试会话列表（排除已删除） |
| GET | `/interview/sessions/{id}` | 会话详情 + checkpointer 历史消息回放 |
| DELETE | `/interview/sessions/{id}` | 删除会话（软删归档） |
| GET | `/interview/sessions/{id}/report` | 面试报告 |
| GET/POST | `/agent/files`、`/upload`、`/batch-upload`、`/parse` | 文件列表/上传/批量上传/解析 |
| GET | `/agent/files/{id}/download` | 文件下载 |
| GET/PUT/DELETE | `/users`、`/roles` | 本租户用户/角色 |
| GET | `/audit/logs` | 本租户审计日志 |
| GET/PATCH | `/messages/queue`、`/messages/dead-letters` | 本租户消息/死信 |

**系统域**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health`、`/api/v1/health` | 探针，免鉴权 |
| GET | `/api/v1/dashboard` | 看板（超管全局/聚焦租户，租户管理员本租户） |

## 9. 认证与权限

身份只有一个来源：`POST /auth/login` 签发的 JWT，`Authorization: Bearer`。后端不读任何身份头，也不给开发默认值。

- 登录会话由 Redis 承载（滑动续期）：签发 JWT 时写 `auth:session:{jti}`；`/auth/logout` 立即失效。
- 普通用户/租户管理员 token 含 `tenant_id`；超管不含租户，业务接口一律 403。
- 授权真源是 `agent_role`、`agent_role_permission`、`agent_user_tenant`；`get_current_user` 解析出 `scopes`。
- 路由防护用 `require_role` / `require_scope`；`admin/**` 整组 `require_super_admin`，`tenant/**` 整组 `require_tenant`。
- 存储隔离：业务/记忆按 `tenant_id` 行级过滤；Milvus 用 partition key；Redis 用 `t:{tenant_id}:` 前缀。
- Agent 可用性 = `agent.enabled` AND 租户 `agent_capability_policy`（未配置视为开通）AND 调用方 scope。

详见 `docs/登录与权限校验说明.md`。

## 10. 数据层

`schema.sql` 由 `scripts/gen_schema.py` 从 `backend/data/postgres` 模型生成，按域分布：

| 域 | 表 |
| --- | --- |
| 身份与权限 | `agent_user`、`agent_user_tenant`、`agent_role`、`agent_role_permission`、`agent_menu`、`agent_login_log`、`agent_api_call_log` |
| 租户 | `agent_tenant` |
| 会话与运行 | `agent_thread`、`agent_run`、`agent_message`、`agent_long_term_memory`、`agent_escalation` |
| Agent 与能力 | `agent`、`agent_capability_policy`、`agent_tool`、`agent_plugin` |
| 模型 | `agent_model`、`agent_model_registry` |
| 业务 | `agent_exams`、`agent_exam_submissions`、`agent_exam_reviews`、`agent_questions`、`agent_scoring_points`、`agent_resume_reviews`、`agent_interview_sessions`、`agent_interview_questions`、`agent_qa_results`、`agent_qa_ragas_evals` |
| 配置中心 | `agent_config_approval`、`agent_config_review` |
| 消息 | `agent_outbox`、`agent_dead_letter` |
| 审计与知识 | `agent_audit_log`、`agent_knowledge_pending_queue` |

- DAO 按域放在 `backend/data/dao/{auth,agent,business,ops}`，全部手写 SQL。
- `schema.sql` 末尾带种子：主租户、admin 账号、角色与权限点、菜单树、Agent 登记、模型登记。
- `updated_at` 由 `set_updated_at()` / `update_updated_at_column()` 触发器刷新；不再使用 `WHEN (OLD IS DISTINCT FROM NEW)`（json 列没有 `=`，会导致任何 UPDATE 失败）。
- 改表结构流程：改 `data/postgres` 模型 → `python scripts/gen_schema.py` → 重新导入 `schema.sql`。

表结构细节见 `docs/数据库设计文档.md`。

## 11. 管理后台前端

`dashboard/`，Vite + React 18 + TypeScript + Ant Design 5。

| 路由 | 页面 | 状态 |
| --- | --- | --- |
| `/login` | 登录 | 已接 |
| `/dashboard` | 监控概览 | 已接；刷新按钮强制回源 |
| `/agents/list` | 智能体管理 | 已接；缺详情/租户策略 UI |
| `/tools` | 工具与插件 | 已接清单/启停；缺调用统计 |
| `/models` | 模型注册表 | 已接 |
| `/users`、`/tenants`、`/roles`、`/menus` | RBAC 与租户 | 已接 |
| `/config/*` | 配置中心 | 已接 |
| `/audit/operation`、`/audit/login`、`/audit/api` | 业务/登录/API 审计 | 已接；ID 映射名称、支持筛选 |
| `/messages/queue`、`/messages/dead-letters` | 消息/死信 | 已接；固定列、状态/模式筛选、失败原因 |
| `/agent/qa/*` | QA 文件/结果/问答/会话 | 已接；SSE、停止、动态加载 |
| `/agent/resume/analysis` | 简历列表/报告 | 已接；上传、轮询、报告、删除 |
| `/agent/exam/*` | 考试发起/结果/报告 | 后端已接，前端仍 mock |
| `/agent/resume/upload`、`/resume/*` | 旧简历入口 | 兼容保留 |

- token 存 `localStorage.ap_token`，会话信息存 `ap_session`；任意 401 清 token 回登录页。
- 请求层 `services/http.ts` 主动带 `X-Trace-Id`，后端 trace 中间件透传。
- 所有 ProTable 列表统一支持「固定列」选择（`components/ProTable.tsx`），默认固定前两列。
- 左侧菜单由登录响应 `menus` 驱动，不再代码写死。
- 逐页测试要点见 `docs/前端页面接口对接现状与测试清单.md`。

## 12. 离线模块

`offline/` 只负责产出模型产物，在线只消费，**不 import 任何 `backend` 代码**。

```bash
python -c "from offline import list_tasks, run_task; print(list_tasks()); run_task('intent_training')"
```

| 功能块 | 状态 |
| --- | --- |
| `intent_training` | 已实现：微调 bert-base-chinese，产物写 `models/` |
| `intent_eval` | 已实现：准确率 / 分类报告 / 混淆矩阵 → `metrics.json` |
| `review` | 未实现：`run()` 抛 `NotImplementedError` |
| `agent_audit` | 未实现：同上 |

在线侧由 `LLMFactory.classify()` 懒加载产物（读 `meta.json` 取标签顺序与 `max_len`）。

## 13. 测试

```bash
make test        # pytest -q
make format      # ruff format + ruff check --fix
```

测试不依赖真实中间件（DAO 与客户端用 AsyncMock 替身）。覆盖 schema.sql 与模型一致性、登录日志、菜单与角色、看板统计、权限映射、身份解析、记忆隔离、就绪自检、审计 SQL 等。

## 14. 已知限制

1. `deploy/Dockerfile` 的 gunicorn 入口是 `backend.main:app_state.fastapi_app`，该属性要到 `AppServer.start_all` 才赋值；更稳的是 `python backend/main.py`。
2. `make dev` 固定 8000，`.env` 里的 `PORT` 对它不生效，注意和前端代理一致。
3. 后端未配置 CORS，前端只能走 Vite 代理（开发）或同域反代（生产）。
4. `DOCS_ENABLED` 默认 False，本地要看 Swagger 需在 `.env` 打开。
5. 模型注册表的 `api_key` 出参为 `***`，前端编辑留空表示保留原 key。
6. `agent_run` 尚未写入，Token 消耗/真实业务成功率/租户用量排行暂无本地台账；看板当前用 API 日志兜底。
7. 业务审计未覆盖 QA/简历/文件等业务操作；看板「最近活动」会在审计不足时混入 API 调用记录。
