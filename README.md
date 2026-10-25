# agent-platform

多 Agent 编排系统（EduAgent 业务蓝本）。多模块、单应用：一个 FastAPI 应用内做 LangGraph 图编排、插件化能力缝隙、分层记忆、RAG 复用。

设计文档见 `docs/多 Agent 系统架构设计方案.md`。脚手架对应里程碑 **M0**：`backend/` 单应用骨架 + AppServer/Manager 启动范式。

## 系统架构

多 Agent 编排系统采用分层架构，各层职责清晰、协同高效。核心要点：**Orchestrator 即 Supervisor**（意图识别 + 多 Agent 管道编排），下辖 QA / Exam / Resume / Interview 四类 **Worker**；数据访问前经 **Redis 缓存层**，尽量让查询不落到数据库。

```
┌───────────────────────────────────────────────────────────┐
│                     Web UI (User Interface)               │
└──────────────────────────────┬────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────┐
│                       API Layer (FastAPI)                 │
│    Authentication / Request Routing / Streaming Response  │
└──────────────────────────────┬────────────────────────────┘
                               │
╔══════════════════════════════▼════════════════════════════╗
║   Orchestrator  ──  Supervisor                            ║
║   Intent Recognition / Multi-Agent Pipeline Orchestration ║
║                                                           ║
║        ┌────────┐  ┌────────┐  ┌────────┐  ┌──────────┐   ║
║        │   QA   │  │  Exam  │  │ Resume │  │Interview │   ║
║        └────┬───┘  └────┬───┘  └────┬───┘  └────┬─────┘   ║
║             └───────────┴───────────┴───────────┘  Worker ║
╚═══════════════════════════════════════════════════════════╝
                               │
┌──────────────────────────────▼────────────────────────────┐
│                        Common Layer                       │
│    LLM Factory / Local Model / Memory Management / Retry  │
└──────────────────────────────┬────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────┐
│                          MCP Layer                        │
│       Knowledge Base Retrieval Tool / Web Search Tool     │
└──────────────────────────────┬────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────┐
│                    Redis  (缓存层 / Cache)                │
│        读缓存优先，尽量让查询不落到数据库（DB）           │
└───────┬─────────────────────┬─────────────────────┬───────┘
        │                     │                     │
┌───────▼───────┐     ┌───────▼───────┐     ┌───────▼───────┐
│    Milvus     │     │  PostgreSQL   │     │    MongoDB    │
│   向量检索    │     │ 业务/元数据/RBAC│    │  文档 / 轨迹  │
└───────────────┘     └───────────────┘     └───────────────┘
```

**分层职责**

- **Web UI**：用户交互入口。
- **API Layer (FastAPI)**：认证（JWT 验签 + 查库授权）、请求路由、流式响应。
- **Orchestrator（Supervisor）**：意图识别 + 多 Agent 管道编排，按意图路由到 Worker。
- **Worker**：QA / Exam / Resume / Interview 四类业务 Agent，独立图编排、可插拔。
- **Common Layer**：LLM 工厂、本地模型（规划中）、记忆管理、重试（**待实现**）。
- **MCP Layer**：知识库检索、联网搜索等工具，统一工具协议与错误边界。
- **Redis 缓存层**：热点查询优先命中缓存，尽量让读请求不落到数据库。
- **数据层**：Milvus（向量检索）、PostgreSQL（业务/元数据/RBAC）、MongoDB（文档/运行轨迹，规划中）。

## 待实现 / 规划项

- **Retry 重试**（Common Layer）：模型/工具层异常重试机制尚未落地（仅 `llm_factory` 文档提及，无实际重试循环），列为**待实现**。
- **本地模型推理服务**（Common Layer）：当前 LLM 走外部 API，未接入本地推理服务（如 vLLM）；离线意图分类器属独立本地 HF 模型，不在此列。
- **MongoDB 轨迹/文档存储**（数据层）：架构图含，但当前代码未接入，审计/轨迹暂存 PostgreSQL。
- **Web UI**：架构含前端层，本仓库为后端/API，前端不在本仓。

## 模块边界

- `backend/server`：AppServer + 各 XXManager，`register(manager, order)` 顺序启动、优雅启停、fail-fast。
- `backend/config`：ConfigManager，经 `python-dotenv`（`load_dotenv(override=True)`）将 `.env` 载入 `os.environ`，再 env/YAML + Pydantic 校验 → `app_state.settings`。
- `backend/orchestration`：Orchestrator（Supervisor）+ AgentRegistry，意图识别与多 Agent 管道编排。
- `backend/common`：Common 层 —— LLM 工厂（`common/llm`）、记忆管理（`common/memory`）、配置中心（`common/config_center`）。
- `backend/security`：认证与 RBAC（`security/rbac`、`security/security`）。
- `backend/observability`：异常与 trace（`observability/exception`、`observability/tracing`）。
- `backend/agents`：四类业务 Agent（resume/qa/exam/interview），各为受控 LangGraph 图。
- `backend/mcp`：MCP 层 —— 工具协议（`mcp/protocol`、`mcp/registry`）、内置工具（`mcp/builtin`：web_search/code_exec）、知识库检索（`mcp/retrieval`）、外部插件挂载点（`mcp/external`）。
- `backend/data`：Data 层 —— ORM 模型（`data/postgres`）、向量存储（`data/milvus`）、数据访问（`data/dao`）；模型与 DAO 均按 `auth` / `agent` / `business` / `ops` 分域存放。
- `backend/middleware`：认证（JWT 验签 + 库查授权）、trace_id、租户级限流。
- `backend/api/v1`：统一入口 + 各 Agent 直连端点 + 运维端点。
- `offline/`：**离线模块**（与在线解耦），按功能块分子包，统一用注册表调度。
- `scripts/`：开发/运维辅助（`gen_schema.py` 生成 `schema.sql`，种子只含角色与超管账号；`gen_dev_curl.py` 拼带 Bearer token 的 curl）。
- `deploy/`：`gunicorn.conf.py` 多 worker 配置（同样经 `load_dotenv` 载入 `.env`）。

## 离线模块 `offline/`

意图识别等「离线生产」与在线业务完全解耦：离线只负责训练/评估并产出模型产物，在线只消费产物。**离线代码不 import 任何 `backend` 代码。**

```
offline/
├─ __init__.py        # 导出 list_tasks / run_task / get_task / register / OfflineConfig
├─ base.py            # OfflineTask(ABC)：功能块统一契约（name/description/run）
├─ registry.py        # 注册表：register / list_tasks / get_task / run_task
├─ requirements.txt   # 离线独立依赖（torch / transformers / scikit-learn / pandas）
├─ common/            # 公共基础设施（被各功能块共享，不单独跑）
│  ├─ config.py        #   OfflineConfig（OFFLINE_* 环境变量覆盖，默认指向项目内路径）
│  ├─ intents.py       #   意图标签 schema（与在线路由对齐）
│  ├─ data.py          #   JSONL 加载 + IntentDataset
│  └─ model.py         #   HF 产物构建/保存/加载（含 meta.json）
├─ tasks/             # ★ 所有离线功能块的家（新增块=建子包+实现+在 __init__ import）
│  ├─ intent_training/ #   离线训练意图分类器（微调 bert-base-chinese → HF 产物）
│  ├─ intent_eval/     #   评估意图模型（准确率/分类报告/混淆矩阵 → metrics.json）
│  ├─ review/          #   评审（人工/HITL 复核，占位骨架）
│  └─ agent_audit/     #   agent 全流程审计（离线回放/分析运行轨迹，★预留位置）
└─ sample_data/intents.jsonl
```

### 设计要点（可扩展）
- 每个功能块是 `offline/tasks/` 下的一个子包，继承 `OfflineTask` 并 `@register` 自注册；其余代码无需改动即可被 `registry` 发现与调度。
- **注册 ≠ 执行**：`offline/tasks/__init__.py` 仅 import 各子包触发注册，不会自动运行任务；每个块独立、可按需单独跑。
- **新增功能块**：在 `offline/tasks/` 下建子包 → 定义 `class XxxTask(OfflineTask)` 实现 `run()` → `@register` → 在 `offline/tasks/__init__.py` 加一行 import。

### 运行（无独立 CLI 启动器，各块以 `main()` 为入口）
```bash
# 方式一：注册表统一调度（按名字跑一个块）
python -c "from offline import list_tasks, run_task; print(list_tasks()); run_task('intent_training')"
from offline import list_tasks, run_task
list_tasks()                 # ['agent_audit','intent_eval','intent_training','review']
run_task("intent_training")  # 跑意图训练
run_task("agent_audit")      # 未来审计（现 NotImplementedError）

# 方式二：直连某块 main（也可 python -m offline.tasks.<block>.task 或直接 python offline/tasks/<block>/task.py）
from offline.tasks.intent_training.task import main as train
train()
```

### 在线消费（解耦边界）
在线 `backend/common/llm/llm_factory.py` 的 `classify()` 按 `MODEL.classifier_dir` **懒加载**离线产物（读 `meta.json` 取标签顺序与 `max_len`），不依赖 `offline` 包。训练产物写入 `models/`（已被 `.gitignore` 忽略，权重不入库）；源码与示例数据入库。

`.env` 配置（离线默认指向项目内路径）：
```
OFFLINE_DATA=offline/sample_data/intents.jsonl
OFFLINE_BASE_MODEL=bert-base-chinese
OFFLINE_MODEL_OUT=models/bert-intent-recognition-model
OFFLINE_EPOCHS=3
OFFLINE_BATCH=16
OFFLINE_LR=0.00002
OFFLINE_MAX_LEN=64
CLASSIFIER_DIR=models/bert-intent-recognition-model   # 在线侧加载目录
```

## 认证与 RBAC

身份只来自 `POST /api/v1/auth/login` 签发的 JWT：后端验签后查库授权，不信任 token 里的角色，也不读任何身份头。

- **身份来源**：只有登录签发的 JWT（`Authorization: Bearer`）。payload 含 `user_id`，普通用户与租户管理员另含 `tenant_id`；超管不含租户且请求期不补租户，只能维护基建数据（租户、用户、角色、菜单、Agent 定义、配置），会话、记忆、QA/chat 一律 403。不再支持信任头与开发默认值。
- **授权真源 = 数据库**（角色/权限不来自 header 或 JWT，永不信任其自带的角色）：
  - `agent_role`（student/teacher/admin）、`agent_role_permission`（角色→权限点，`*` 通配）、`agent_user_tenant`（`(user_id, tenant_id) → role_id`，强制「一用户在单租户只任一角色」）。
  - `get_current_user` → `RbacService.resolve(user_id, tenant_id)` 查三表得 `(role_name, scopes)`，写入 `request.state` 与 contextvars；解析不到分配即 **403**。
- **常量仅作种子源**：`DEFAULT_ROLE_SCOPES` 只用于 `RbacService.ensure_default_roles()` 写入库，请求期授权一律以 `agent_role_permission` 表为准，不参与兜底。`DEV_ROLE` 已移除。
- **路由防护**：`require_role("teacher")` / `require_scope("exam:grade")`（详见 `backend/security/security.py`）。
- **存储隔离**：业务/记忆按 `tenant_id` 行级过滤，Milvus 用 partition key，Redis 用 `t:{tenant_id}:` 前缀。

数据须提前录入（二选一）：
```bash
psql "$DATABASE_URL" -f scripts/seed_rbac.sql        # 幂等建三角色 + 分配（含 dev-user/dev-tenant/admin）
# 或启动后调 RbacService.ensure_default_roles()（幂等播种角色+权限点），再补 agent_user_tenant 分配行
```

## 配置加载

统一经 `python-dotenv`：
- `backend/config/settings.py`：`load_dotenv(dotenv_path=BASE_DIR/".env", override=True)` 后再读 `os.environ`。
- `offline/common/config.py`、`scripts/gen_dev_curl.py`、`deploy/gunicorn.conf.py`：各自进程启动即 `load_dotenv(override=True)`。
- `override=True` 语义：`.env` 中的同名项**覆盖**已有 shell 环境变量（若需 shell 环境变量优先，改 `override=False`）。
- 依赖：`python-dotenv` 已加入 `pyproject.toml`；新环境需重新 `pip install -e .`。

## 启动

```bash
conda activate agent_platform
make install                 # pip install -e ".[dev]"（含 python-dotenv）
cp .env.example .env         # 按需填写（含 OFFLINE_* / CLASSIFIER_DIR / DEV_*）
docker compose up -d         # postgres / redis / milvus
make dev                     # uvicorn backend.main:app --reload --port 8000
```

## 开发辅助

- `scripts/seed_rbac.sql`：幂等建角色与分配（见「认证与 RBAC」）。
- `scripts/gen_dev_curl.py`：用 `.env` 的 `JWT_SECRET` 现签 token 拼出 curl，验证认证链路。
  ```bash
  # 身份一律由命令行传入，不读 .env 的固定 id
  python scripts/gen_dev_curl.py --user-id 1 /api/v1/admin/config/requests              # 超管 token
  python scripts/gen_dev_curl.py --user-id 2 --tenant-id 1 /api/v1/admin/config/requests  # 租户 token
  python scripts/gen_dev_curl.py --user-id 1 /api/v1/admin/config/requests --run        # 直接执行
  ```

## 运行范式（复用 RAG-Ultra）

`AppServer` 注册多个 `XXManager`，按 order 顺序启动、逆序停机；任一启动项失败即整体 fail-fast。配置集中由 `ConfigManager` 加载（经 `load_dotenv` 载入 `.env`），其余模块只消费 `app_state.settings`。
