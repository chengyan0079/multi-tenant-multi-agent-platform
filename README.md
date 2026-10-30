# 多租户多智能体协作平台

多租户多智能体协作平台。单仓三块：`backend/` 一个 FastAPI 应用、`dashboard/` 管理后台前端（React + Ant Design）、`offline/` 意图模型离线训练与评估。

本文件按**代码实际状态**写：已装配能跑的写在前面，骨架、占位、未装配集中在「未实现」一节，不做完成度包装。设计与表结构见 `docs/`。

## 1. 现在能跑什么

| 能力 | 入口 | 说明 |
| --- | --- | --- |
| 登录与身份 | `POST /api/v1/auth/login`、`GET /auth/me`、`GET /auth/menus` | 账号密码校验（bcrypt），签发 JWT；每次尝试（成功/失败）都落 `agent_login_log` |
| 认权 | 路由装配处统一挂依赖 | JWT 验签后查三张 RBAC 表得 `scopes`，token 内的角色不参与授权 |
| 管理后台 API | `/api/v1/admin/**` 共 9 组 | 租户、用户/角色、菜单、Agent 定义与开通策略、插件清单、模型注册表、审计、配置中心审批流 |
| 租户侧 API | `/api/v1/tenant/**` | 会话、转人工、租户用户/角色/审计、编排入口（可用性见第 2 节） |
| 监控看板 | `GET /api/v1/dashboard` | 超管看全局，租户管理员看本租户 |
| 审计与请求日志 | `agent_audit_log`、`agent_api_call_log` | 管理动作由 `AuditDao` 显式写审计表；业务表统一注入审计列（create/update_user_id、tenant_id），非请求期缺值直接报错不兜底；中间件记录请求元数据 |
| 配置中心 | `/api/v1/admin/config/**` | 申请 → 复核 → 执行三步，只有「执行」真正写 Nacos；支持回滚到历史版本 |
| 模型注册表 | `/api/v1/admin/models/**` | 四类模型（llm/embedding/reranker/classifier）的 active 记录驱动运行时，api_key 出参脱敏 |
| Nacos | `nacos_discover_manager`、`nacos_config_manager` | 服务注册发现（独立命名空间）+ 配置中心（独立命名空间） |
| 日志 | `backend/common/logger.py` | loguru，控制台+文件双写，含 time/level/pid/thread/trace_id/位置 |
| 离线意图模型 | `offline/tasks/intent_training`、`intent_eval` | 微调 bert-base-chinese、评估出 metrics.json；在线按 `CLASSIFIER_DIR` 懒加载 |
| 管理后台前端 | `dashboard/`，12 页 | 9 页已接真实接口，3 页未完成（见 `docs/前端页面接口对接现状与测试清单.md`） |
| 测试 | `tests/`，15 个测试文件 | pytest + pytest-asyncio；含 schema 校验、权限映射、审计 SQL 等 |

## 2. 还没实现（含「代码在但没装配」）

`backend/server/register.py` 里有 6 个启动项被注释，这是很多能力「看着有、实际不通」的根因：

| 未注册的 Manager | 导致的现状 |
| --- | --- |
| `OrchestratorManager` | `app_state.orchestrator` / `agent_registry` 恒为 `None`。`POST /tenant/chat` 能过前置拦截与意图分类，到分发那一步返回 SSE `error` 事件；多 Agent 串联跑不起来 |
| `CheckpointerManager` | 无 LangGraph checkpointer，多轮上下文与 HITL 恢复不可用 |
| `PluginManager` | `app_state.plugin_registry` 为 `None`，MCP 工具注册表为空，QA 的 web 兜底直接跳过 |
| `MemoryManager` | 短期记忆（Redis）、长期记忆（Milvus）都没接 |
| `RagAdapterManager` | RAG 适配层未装配，检索走空结果降级 |
| `ObservabilityManager` | tracing 只有空 span 占位，未接 Langfuse |

其余未实现项：

| 项 | 现状 |
| --- | --- |
| 四类 Agent 直连端点 | `/tenant/qa/ask`、`/tenant/resume/analyze`、`/tenant/exam/grade`、`/tenant/interview/start` 只回显入参，不执行图 |
| Agent 节点逻辑 | QA 生成、Resume 评分、Web 兜底结果均为占位；图结构（state/graph/nodes）是真的 |
| MCP 内置工具 | `web_search`、`code_exec` 是占位实现，调用返回空或「未实现」，由注册表降级不阻断 |
| LLM 路由 | 模糊意图的 LLM 路由写死为 `qa`，未实现真正的模型分类 |
| 长期记忆 | Milvus 客户端能连，但记忆读写链路未启用 |
| MinIO | 有 S3 客户端封装，业务未使用 |
| 运维能力 | 只有 `/health` 汇总组件状态，没有指标与日志查询接口 |
| 前端 3 页 | `/agents`（缺详情、缺租户开通策略 UI）、`/tools`（缺启停与调用统计）、`/sessions`（仍是假数据） |
| 离线两块 | `offline/tasks/review`、`offline/tasks/agent_audit` 调 `run()` 抛 `NotImplementedError` |

## 3. 架构与装配现状

```
Browser / curl
      │  Authorization: Bearer <JWT>
      ▼
FastAPI  backend/api/router.py → /api/v1
   ├── admin/**   整组 require_super_admin
   ├── tenant/**  整组 require_tenant（超管 403）
   ├── auth/**    /login 公开，/menus /me 挂 get_current_user
   └── health、dashboard（免鉴权 / 限超管或租户管理员）
      │
      ├── middleware：trace_id → api_log（落库）→ 限流（slowapi）
      ├── security：JWT 验签 → RBAC 三表查库 → scopes → require_scope
      ▼
Orchestrator（未装配）── AgentRegistry（未装配）
      ├── QA / Resume / Exam / Interview：LangGraph 图，节点部分占位
      ├── MCP 工具（未装配）  RAG 适配（未装配）  Memory（未装配）  Checkpointer（未装配）
      ▼
PostgreSQL（32 张表，手写 SQL）  Redis（提示词缓存/短期记忆）  Milvus（长期记忆，未启用）  Nacos（发现+配置）
```

启动顺序（`backend/server/register.py`，同 order 并行、跨 order 串行，失败即 fail-fast 并回滚）：

| order | 组件 |
| --- | --- |
| 10 | Logging |
| 20 | Redis、PostgreSQL、Model（LLM 工厂）、Security |
| 30 | Milvus |
| 50 | FastAPI（挂载全部路由） |
| 60 | Nacos 配置中心 |
| 70 | Nacos 服务发现 |

## 4. 目录结构

```
backend/
├─ main.py                 入口：AppServer 装配 + uvicorn
├─ app_state.py            进程级单例（各 Manager 启动时写入）+ 请求上下文 contextvars
├─ server/                 AppServer / BaseManager / register.py / managers/*
├─ config/                 pydantic-settings 读 .env → config 单例
├─ api/
│  ├─ router.py            按 admin / tenant / auth / 系统域分组挂载，鉴权只在装配处挂一次
│  └─ v1/{admin,tenant,auth}/、dashboard.py、health.py
├─ agents/{qa,resume,exam,interview}/   state + graph + nodes + api
├─ orchestration/          Orchestrator（单 Agent 直达 / 多 Agent 串联 / HITL 恢复）+ AgentRegistry
├─ mcp/                    protocol / registry / builtin / retrieval / external
├─ common/                 llm（四模型工厂）/ memory / config_center（Nacos 审批与提示词缓存）/ logger / response
├─ security/               rbac（角色与权限点）/ security（JWT、依赖、输入护栏）
├─ middleware/             auth / trace_id / api_log / rate_limit
├─ observability/          exception（错误码与异常类）/ tracing（占位）
└─ data/                   clients（pg/redis/milvus/minio/nacos）/ dao（按域）/ postgres（模型，仅用于生成 DDL）/ sql
dashboard/                  Vite + React + Ant Design 管理后台
offline/                    离线训练/评估，不 import backend
scripts/                    gen_schema.py（生成 schema.sql）、gen_dev_curl.py
tests/                      pytest
deploy/                     Dockerfile + gunicorn.conf.py
docs/                       架构设计、数据库设计、登录与权限、前端对接现状
```

## 5. 技术栈

- 后端：Python 3.12、FastAPI、pydantic-settings、SQLAlchemy(asyncpg) 手写 SQL、LangGraph/LangChain、sse-starlette、slowapi、loguru、nacos-sdk-python
- 存储：PostgreSQL（业务/权限/审计/checkpoint）、Redis（缓存/短期记忆）、Milvus（向量）、MinIO（对象存储，未启用）
- 模型：LLM 走 OpenAI 兼容接口（`ChatOpenAI` + base_url），嵌入/重排/意图分类为 bge-m3、bge-reranker-v2-m3、bert-base-chinese
- 前端：React 18、TypeScript、Ant Design 5、Recharts、Vite 5
- 质量：pytest、ruff（line-length 100）

数据访问约定：运行时**不用 ORM**，DAO 全部 `text()` 手写 SQL；`data/postgres` 下的模型只供 `scripts/gen_schema.py` 生成 `schema.sql`。

## 6. 快速开始

```bash
# 1) 依赖
conda create -n agent_platform python=3.12 -y && conda activate agent_platform
pip install -e ".[dev]"

# 2) 配置
cp .env.example .env        # 至少填 JWT_SECRET、POSTGRES_*、NACOS_*

# 3) 中间件（PostgreSQL / Redis / Milvus + etcd + minio）
docker compose up -d

# 4) 建库与种子（建表 + 角色/权限点/菜单/主租户/admin/模型登记）
#    账号密码与 docker-compose.yml 一致：agent / agent_pass / agent_platform
psql -h localhost -U agent -d agent_platform -f scripts/schema.sql
# schema.sql 由 python scripts/gen_schema.py 从模型生成，改表结构后重新生成

# 5) 启动后端（端口取 .env 的 PORT）
python backend/main.py

# 6) 启动前端（另开终端）
cd dashboard && npm install && npm run dev
```

- 后端默认 `PORT=8000`；本仓库 `.env` 现为 `9800`，`dashboard/vite.config.ts` 的代理也指向 `9800`，改端口要同步改代理。
- `make dev` 固定跑 `uvicorn backend.main:app --reload --port 8000`，不读 `PORT`，和自己改过的 `.env` 容易打架，日常建议直接用 `python backend/main.py`。
- 前端固定 `5173`，只代理 `/api` 与 `/v1`；后端没有配 CORS，生产环境需让前端与 API 同域（同域反代或静态托管到同一域名）。
- 启动会做模型就绪自检：`agent_model_registry` 中 llm / embedding / reranker / classifier 各需至少一条 `enabled=true`，缺任一类直接启动失败。
- 种子账号：`admin / 123456`（超管，无租户）。Nacos 需自备（默认 `http://localhost:8848`），不启动时把 `NACOS_ENABLED`、`NACOS_CONFIG_ENABLED` 置 False。

## 7. 配置

统一由 `backend/config/schemas.py`（pydantic-settings）读 `.env`，按分组加前缀；其余模块只消费 `config` 单例。

| 分组 | 前缀 | 关键项 |
| --- | --- | --- |
| 服务 | `SERVICE_*` / `PORT` / `VERSION` | `SERVICE_IP`、`PORT`、`DOCS_ENABLED`（True 才暴露 /docs） |
| PostgreSQL | `POSTGRES_` | host / port / user / password / db；`search_path` 走连接参数 |
| Redis | `REDIS_` | host / port / password；提示词缓存与短期记忆共用 |
| Milvus | `MILVUS_` | host / port / db_name / collection；嵌入维度与 RRF 权重也在此 |
| RAG 检索 | `RAG_` | `MCP_URL` / `IMPORT_PATH` / `HTTP_BASE`，二选一 |
| MinIO | `MINIO_` | endpoint / bucket / access_key / secret_key |
| 安全 | `JWT_` | secret / algorithm / expire_minutes |
| 可观测 | `LANGFUSE_` | host 与密钥（tracing 尚未接） |
| Nacos 发现 | `NACOS_` | enabled / server_addr / namespace / group / `DISCOVER_STRICT` |
| Nacos 配置 | `NACOS_CONFIG_` | enabled / server_addr / namespace / group / 账号 |
| 日志 | `LOG_*` | level / file / size / file_days；相对路径以项目根为基准 |
| API 日志 | `API_LOG_*` | enabled / db / save_body / max_body / exclude |
| 离线 | `OFFLINE_*` | data / base_model / model_out / epochs / batch / lr / max_len |

## 8. API 概览

全部在 `/api/v1` 下。返回统一信封 `{code, msg, data}`；业务失败是 HTTP 200 + `code != 0`，鉴权失败是 401/403。

**认证** `/auth`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/login` | body `{username, password, tenant_id?}` |
| GET | `/me` | 当前身份（用户、租户、角色、scopes） |
| GET | `/menus` | 按 scopes 过滤的菜单树 |

**基建域** `/admin`（整组 super_admin）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/agents` | Agent 列表，可带 `tenant_id` 查开通状态 |
| GET | `/agents/{type}` | Agent 详情 |
| PATCH | `/agents/{type}/enabled` | 全局启停（落库，registry 未装配时只写库） |
| GET/PUT | `/agents/tenants/{id}/capabilities` | 租户级开通策略 |
| GET | `/plugins` | 已注册工具能力名清单 |
| GET/POST | `/models` | 列表（可按类型筛）/ 新增 |
| GET/PUT/DELETE | `/models/{id}` | 详情 / 更新 / 删除 |
| GET/POST | `/tenants` | 租户列表（含管理员与用户数）/ 新建 |
| PUT | `/tenants/{id}` | 改名 / 启停 |
| PUT | `/tenants/{id}/manager` | 指定或更换租户管理员 |
| GET | `/users` | 全量用户（分页、条件筛选） |
| PUT | `/rbac/users/{id}/role` | 改任意租户内用户角色 |
| GET/POST | `/roles` | 角色目录（含权限点）/ 新建 |
| PUT | `/roles/{id}/permissions` | 覆盖角色权限点 |
| DELETE | `/roles/{id}` | 删除非内置角色 |
| GET/POST | `/menus` | 菜单树（含隐藏）/ 新建 |
| PUT/DELETE | `/menus/{id}` | 更新 / 删除 |
| POST | `/config/requests` | 发起配置变更申请 |
| POST | `/config/requests/rollback` | 发起回滚申请 |
| GET | `/config/requests`、`/requests/{id}` | 申请列表 / 详情（含 Nacos 实时内容对比） |
| POST | `/config/requests/{id}/review` | 复核（通过 / 驳回） |
| POST | `/config/requests/{id}/execute` | 执行（真正写 Nacos） |
| GET | `/audit/logs` | 审计日志（可按租户筛，limit ≤ 1000） |

**业务域** `/tenant`（整组需租户 token，超管 403）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/chat` | 统一问答入口，SSE 流式；事件：routing_decision / progress / meta / done / error |
| GET | `/threads/{id}` | 会话状态 |
| POST | `/threads/{id}/resume` | HITL 恢复 |
| GET | `/escalations` | 转人工工单列表 |
| POST | `/orchestrator/run`、`/resume` | 编排直接入口（依赖未装配的 Orchestrator） |
| POST | `/qa/ask`、`/resume/analyze`、`/exam/grade`、`/interview/start` | 四类 Agent 直连，目前是回显桩 |
| GET/POST | `/users` | 本租户用户列表 / 建普通用户 |
| PUT | `/users/{id}/role` | 改本租户内角色（student/teacher） |
| DELETE | `/users/{id}` | 从本租户解绑 |
| GET | `/roles` | 本租户可分配角色 |
| GET | `/audit/logs` | 本租户审计日志 |

**系统域**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health`、`/api/v1/health` | 探针，免鉴权；汇总各组件状态 |
| GET | `/api/v1/dashboard` | 看板数据（超管全局 / 租户管理员本租户） |

## 9. 认证与权限

身份只有一个来源：`POST /auth/login` 签发的 JWT，`Authorization: Bearer`。后端不读任何身份头，也不给开发默认值。

- 登录会话由 Redis 承载（滑动续期）：`/auth/login` 签发 JWT 时一并写入 `auth:session:{jti}`（TTL 默认 900s，可由 `SESSION_TTL_SECONDS` 调）；每次请求校验通过后重置 TTL，**15 分钟无操作才失效，token 本身不变、前端无感**。`/auth/logout` 删该 key 使当前 token 立即失效，多端各自独立。jti 缺失的旧 token（本功能上线前签发）跳过 Redis 校验、仅按 JWT 验签，兼容到期。
- `payload` 含 `user_id`；普通用户与租户管理员另含 `tenant_id`，超管不含租户、请求期也不补，业务接口一律 403。
- 授权真源是数据库三张表：`agent_role`（角色）、`agent_role_permission`（角色→权限点，支持 `*`）、`agent_user_tenant`（用户在某租户下的角色，一用户一租户只一个角色）。
- `get_current_user` 验签后调 `RbacService.resolve()` 查三表得 `(role_name, scopes)`，写入 `request.state` 与 contextvars；解析不到分配即 403。
- 代码里的 `DEFAULT_ROLE_SCOPES` 只用于幂等播种角色与权限点，不参与请求期鉴权兜底。
- 路由防护用 `require_role(...)` / `require_scope(...)`；`admin/**` 整组 `require_super_admin()`，`tenant/**` 整组 `require_tenant()`。
- 存储隔离：业务与记忆按 `tenant_id` 行级过滤，Milvus 用 partition key，Redis 用 `t:{tenant_id}:` 前缀。

详见 `docs/登录与权限校验说明.md`。

## 10. 数据层

`schema.sql` 共 32 张表，按域分布：

| 域 | 表 |
| --- | --- |
| 身份与权限 | `agent_user`、`agent_user_tenant`、`agent_role`、`agent_role_permission`、`agent_menu`、`agent_login_log`、`agent_api_call_log` |
| 租户 | `agent_tenant` |
| 会话与运行 | `agent_thread`、`agent_message`、`agent_run`、`agent_qa_sessions`、`agent_escalation`、`agent_long_term_memory` |
| Agent 与能力 | `agent`、`agent_capability_policy`、`agent_tool`、`agent_plugin` |
| 模型 | `agent_model`、`agent_model_registry` |
| 业务 | `agent_exams`、`agent_exam_submissions`、`agent_exam_reviews`、`agent_questions`、`agent_scoring_points`、`agent_resume_reviews`、`agent_interview_sessions`、`agent_interview_questions` |
| 配置中心 | `agent_config_approval`、`agent_config_review` |
| 审计与知识 | `agent_audit_log`、`agent_knowledge_pending_queue` |

- DAO 按域放在 `backend/data/dao/{auth,agent,business,ops}`，全部手写 SQL。
- `schema.sql` 末尾带种子：主租户、admin 账号、三角色与权限点、菜单树、Agent 登记、模型登记。
- 改表结构流程：改 `data/postgres` 模型 → `python scripts/gen_schema.py` → 重新导入 `schema.sql`。

表结构细节见 `docs/数据库设计文档.md`。

## 11. 管理后台前端

`dashboard/`，Vite + React 18 + TypeScript + Ant Design 5。

| 路由 | 页面 | 状态 |
| --- | --- | --- |
| `/login` | 登录 | 已接 |
| `/dashboard` | 监控概览 | 已接 |
| `/models` | 模型注册表 | 已接 |
| `/users`、`/tenants`、`/roles`、`/menus` | RBAC 与租户 | 已接 |
| `/config` | 配置中心 | 已接 |
| `/audit` | 审计日志 | 已接 |
| `/agents` | 智能体管理 | 部分：列表 + 启停可用，缺详情与租户策略 UI |
| `/tools` | 工具与插件 | 部分：只读能力名清单 |
| `/sessions` | 会话运行 | 未接：仍是本地假数据 |

- token 存 `localStorage.ap_token`，会话信息存 `ap_session`；任意 401 清 token 回登录页。
- 请求层 `services/http.ts` 只认 `{code,msg,data}` 信封，`code != 0` 当业务错误抛出。
- 左侧菜单目前是代码写死，`GET /auth/menus` 的返回值没有渲染。
- 逐页测试要点与未完成项清单见 `docs/前端页面接口对接现状与测试清单.md`。

## 12. 离线模块

`offline/` 只负责产出模型产物，在线只消费，**不 import 任何 `backend` 代码**。功能块用注册表调度：

```bash
python -c "from offline import list_tasks, run_task; print(list_tasks()); run_task('intent_training')"
```

| 功能块 | 状态 |
| --- | --- |
| `intent_training` | 已实现：微调 bert-base-chinese，产物写 `models/` |
| `intent_eval` | 已实现：准确率 / 分类报告 / 混淆矩阵 → `metrics.json` |
| `review` | 未实现：`run()` 抛 `NotImplementedError` |
| `agent_audit` | 未实现：同上 |

新增功能块：`offline/tasks/` 下建子包 → 继承 `OfflineTask` 实现 `run()` → `@register` → 在 `tasks/__init__.py` 加 import。在线侧由 `LLMFactory.classify()` 按 `CLASSIFIER_DIR` 懒加载产物（读 `meta.json` 取标签顺序与 `max_len`），权重不入库（`models/` 已被 gitignore）。

## 13. 测试

```bash
make test        # pytest -q
make format      # ruff format + ruff check --fix
```

15 个测试文件、126 个用例，`126 passed in 8s` 不需要任何中间件（DAO 与客户端全部用 AsyncMock 替身）。覆盖：schema.sql 与模型一致性、登录日志、菜单与角色接口、看板统计、权限映射与身份解析、记忆隔离、就绪自检、审计 SQL。

注意用 `agent_platform` 环境跑，base 环境里没有 pytest 和项目依赖。

## 14. 已知限制

1. `deploy/Dockerfile` 的 gunicorn 入口是 `backend.main:app_state.fastapi_app`，该属性要到 `AppServer.start_all` 才赋值，容器内这样起会拿到 `None`；更稳的是 `python backend/main.py`（容器化启动方式待验证）。
2. `make dev` 固定 8000，`.env` 里的 `PORT` 对它不生效，注意和前端代理（9800）一致。
3. 后端未配置 CORS，前端只能走 Vite 代理（开发）或同域反代（生产）。
4. `DOCS_ENABLED` 默认 False，本地要看 Swagger 需在 `.env` 打开。
5. 模型注册表的 `api_key` 出参为 `***`，前端编辑留空表示保留原 key，不要回写脱敏值。
6. `tenant/chat/unified.py` 的意图 LLM 路由是占位（统一落到 `qa`），真正的模型路由未做。
