# agent-platform

多 Agent 编排系统（EduAgent 业务蓝本）。多模块、单应用：一个 FastAPI 应用内做 LangGraph 图编排、插件化能力缝隙、分层记忆、RAG 复用。

设计文档见 `docs/多 Agent 系统架构设计方案.md`。脚手架对应里程碑 **M0**：`backend/` 单应用骨架 + AppServer/Manager 启动范式。

## 模块边界

- `backend/server`：AppServer + 各 XXManager，`register(manager, order)` 顺序启动、优雅启停、fail-fast。
- `backend/config`：ConfigManager，经 `python-dotenv`（`load_dotenv(override=True)`）将 `.env` 载入 `os.environ`，再 env/YAML + Pydantic 校验 → `app_state.settings`。
- `backend/core`：Orchestrator、AgentRegistry、LLM 工厂、记忆抽象、安全护栏（RBAC）、异常与 trace。
- `backend/agents`：四类业务 Agent（resume/qa/exam/interview），各为受控 LangGraph 图。
- `backend/rag`：rag-ultra 集成适配层（不重建，仅适配）。
- `backend/plugins`：能力缝隙，协议驱动注册 + 错误边界隔离。
- `backend/models`：SQLAlchemy 模型（thread/run/message/plugin/tool/escalation/memory/audit + business）。
- `backend/middleware`：认证（无登录，身份由网关断言 + 库查授权）、trace_id、租户级限流。
- `backend/api/v1`：统一入口 + 各 Agent 直连端点 + 运维端点。
- `offline/`：**离线模块**（与在线解耦），按功能块分子包，统一用注册表调度。
- `scripts/`：开发/运维辅助（`seed_rbac.sql` 角色种子、`gen_dev_curl.py` 拼带身份头的 curl）。
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
在线 `backend/core/llm_factory.py` 的 `classify()` 按 `MODEL.classifier_dir` **懒加载**离线产物（读 `meta.json` 取标签顺序与 `max_len`），不依赖 `offline` 包。训练产物写入 `ml_models/`（已被 `.gitignore` 忽略，权重不入库）；源码与示例数据入库。

`.env` 配置（离线默认指向项目内路径）：
```
OFFLINE_DATA=offline/sample_data/intents.jsonl
OFFLINE_BASE_MODEL=bert-base-chinese
OFFLINE_MODEL_OUT=ml_models/bert-intent-recognition-model
OFFLINE_EPOCHS=3
OFFLINE_BATCH=16
OFFLINE_LR=0.00002
OFFLINE_MAX_LEN=64
CLASSIFIER_DIR=ml_models/bert-intent-recognition-model   # 在线侧加载目录
```

## 认证与 RBAC（无登录）

后端不做登录：身份由上游网关/SSO 断言后注入，后端只「验签 + 查库授权」。

- **身份来源**：① 网关 JWT（`Bearer`，payload 仅含 `user_id`，后端只验签名不验密码）；② 信任头（`TRUST_HEADERS=True` 信 `X-User-Id`/`X-Tenant-Id`，建议 HMAC 防伪造）；③ 开发默认值（`DEV_USER_ID`/`DEV_TENANT_ID` 非空时作为「你是谁」，但仍须库中有对应分配）。
- **授权真源 = 数据库**（角色/权限不来自 header 或 JWT，永不信任其自带的角色）：
  - `agent_role`（student/teacher/admin）、`agent_role_permission`（角色→权限点，`*` 通配）、`agent_user_tenant`（`(user_id, tenant_id) → role_id`，强制「一用户在单租户只任一角色」）。
  - `get_current_user` → `RbacService.resolve(user_id, tenant_id)` 查三表得 `(role_name, scopes)`，写入 `request.state` 与 contextvars；解析不到分配即 **403**。
- **常量仅作种子源**：`DEFAULT_ROLE_SCOPES` 只用于 `RbacService.ensure_default_roles()` 写入库，请求期授权一律以 `agent_role_permission` 表为准，不参与兜底。`DEV_ROLE` 已移除。
- **路由防护**：`require_role("teacher")` / `require_scope("exam:grade")`（详见 `backend/core/security.py`）。
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
- `scripts/gen_dev_curl.py`：读 `.env` 的 `DEV_*` 拼出带身份头的 curl，验证认证链路。
  ```bash
  python scripts/gen_dev_curl.py /api/v1/config/requests          # 生成 curl（默认 POST）
  python scripts/gen_dev_curl.py /api/v1/config/requests --run    # 直接执行
  ```

## 运行范式（复用 RAG-Ultra）

`AppServer` 注册多个 `XXManager`，按 order 顺序启动、逆序停机；任一启动项失败即整体 fail-fast。配置集中由 `ConfigManager` 加载（经 `load_dotenv` 载入 `.env`），其余模块只消费 `app_state.settings`。
