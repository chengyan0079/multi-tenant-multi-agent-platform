# 后端 TODO / 占位清单

> 由 backend 全量扫描整理。代码内不再保留 `TODO` 标记，统一记录在此，避免散落。
> 状态：`未实现` / `占位降级` / `技术说明（非待办）`。

## 一、业务功能未实现 / 占位

| 位置 | 内容 | 状态 |
| --- | --- | --- |
| `services/notification.py` | 通知渠道 email / wecom / webhook / ticket 未实现，`send_notification` 仅记告警 | 未实现 |
| `services/long_term_memory_extractor.py` | 长期记忆抽取默认 LLM 抽取（LONG_MEMORY_EXTRACT_PROMPT），失败降级为 summary 块 | 已实现 |
| `security/security.py` | 违禁词字典为占位，真实清单走配置 / 外部审核插件 | 占位降级 |
| `mcp/builtin/web_search/tool.py` | 接 Tavily 搜索 API（配置存 `agent_tool.config`，缺省降级占位） | 已实现 |
| `mcp/builtin/code_exec/tool.py` | provider 可扩展骨架（内置 http provider），配置存 `agent_tool.config`，缺省降级 | 已实现 |
| `agents/exam/nodes.py` | 未接真实通知渠道（钉钉/企业微信/WebSocket），当前以 DB 状态表达「等待教师复核」 | 未实现 |
| `api/v1/tenant/agent/qa_results.py` | RAGAS 评估的 `evaluator_model` / `dataset_version` 改为请求级可配（默认 qa-default / v1） | 已实现 |
| `services/agent_run.py` | 已清理：删除无投递方的 `AGENT_RUN` 死链路（services/agent_run.py、broker/handlers/agent.py 及 types/topology/handlers 引用） | 已清理 |

## 二、技术性说明（非待办，建议改为普通注释）

| 位置 | 内容 |
| --- | --- |
| `data/dao/auth/{user,tenant,rbac}_dao.py`、`data/dao/agent/{plugin,model,agent}_dao.py` | asyncpg 扩展协议下 `IS NULL + cast` / `ANY` 无法推断参数类型，必须显式 `CAST` |
| `data/dao/agent/thread_dao.py` | `ON CONFLICT DO UPDATE` 仅作占位以触发 `RETURNING`；非法 uuid 直接判「不存在」 |
| `data/dao/business/file_dao.py` | 版本化判定与 `pg_advisory_xact_lock` 并发控制见 `upload` 事务边界 |
| `data/sql/audit.py` | 非请求期写入用 `SYSTEM_USER_ID` 占位审计列 |
| `data/clients/postgres.py` | 三种占位符风格：asyncpg `$1`、psycopg2 `%s`、命名 `:name` |
| `api/v1/tenant/agent/files.py` | 上传结果来自本次内存结果而非 DB 查询，无法走 `fetch_page` |
| `server/managers/security_manager.py` | 认证/护栏在请求期生效，启动项仅校验配置 |
| `server/managers/fastapi_manager.py` | 不在 FastAPI lifespan 做启动，避免与 AppServer 冲突 |
| `server/managers/model_manager.py`、`common/llm/llm_factory.py` | 全局默认 LLM 仅作向后兼容，per-agent 走 `get_llm(agent_type)` |
| `agents/interview/nodes.py`、`agents/resume/nodes.py` | 题干缺省占位 / 匹配度「暂不可用」降级文案 |

## 三、抽象方法（`NotImplementedError`，非待办）

`server/base_manager.py`、`agents/base.py`、`mcp/protocol.py`、`data/clients/base.py` —— 抽象基类方法，由子类实现。

## 四、提示词内容（非待办）

`agents/exam/prompts.py`（「未实现题目要求」属评分标准文案）、`agents/interview/prompts.py`（「XXX」属提示词占位示例）—— 属提示词正文，不是代码待办。
