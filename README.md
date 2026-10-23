# agent-platform

多 Agent 编排系统（EduAgent 业务蓝本）。多模块、单应用：一个 FastAPI 应用内做 LangGraph 图编排、插件化能力缝隙、分层记忆、RAG 复用。

设计文档见 `docs/多 Agent 系统架构设计方案.md`（v2.3）。脚手架对应里程碑 **M0**：`backend/` 单应用骨架 + AppServer/Manager 启动范式。

## 模块边界

- `backend/server`：AppServer + 各 XXManager，`register(manager, order)` 顺序启动、优雅启停、fail-fast。
- `backend/config`：ConfigManager，env/YAML + Pydantic 校验 → `app_state.settings`。
- `backend/core`：Orchestrator、AgentRegistry、LLM 工厂、记忆抽象、安全护栏、异常与 trace。
- `backend/agents`：四类业务 Agent（resume/qa/exam/interview），各为受控 LangGraph 图。
- `backend/rag`：rag-ultra 集成适配层（不重建，仅适配）。
- `backend/plugins`：能力缝隙，协议驱动注册 + 错误边界隔离。
- `backend/models`：SQLAlchemy 模型（thread/run/message/plugin/tool/escalation/memory/audit + business）。
- `backend/middleware`：认证、trace_id、租户级限流。
- `backend/api/v1`：统一入口 + 各 Agent 直连端点 + 运维端点。

## 启动

```bash
conda activate agent_platform
make install
cp .env.example .env   # 按需填写
docker compose up -d   # postgres / redis / milvus
make dev
```

## 运行范式（复用 RAG-Ultra）

`AppServer` 注册多个 `XXManager`，按 order 顺序启动、逆序停机；任一启动项失败即整体 fail-fast。配置集中由 `ConfigManager` 加载，其余模块只消费 `app_state.settings`。
