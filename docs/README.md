# 文档索引

> 本目录文档用于设计追溯与实现对照。**代码是唯一事实来源**：文档与实现不一致时以代码为准，并回补文档。
> 最后整理：2026-11-16（业务已收敛为「知识问答 / 变更评审 / 变更发布」三个 Agent）。

## 一、现行文档

| 文档 | 内容 | 状态 |
|---|---|---|
| [统一咨询入口设计方案.md](./统一咨询入口设计方案.md) | 统一编排层 + 独立执行图、SSE 事件协议、HITL、会话与记忆、数据模型 | 现行（历史章节含已下线的面试/考试/简历，见文首「现状校准」） |
| [数据库变更与发布治理智能体-执行方案.md](./数据库变更与发布治理智能体-执行方案.md) | 评审 / 发布的业务流程、风险分级、沙箱验证与放行 | 现行 |
| [数据库设计文档.md](./数据库设计文档.md) | 表结构、字段含义、索引与约定 | 现行（教育业务域表已下线，见文首「现状校准」） |
| [登录与权限校验说明.md](./登录与权限校验说明.md) | JWT、RBAC、权限点与菜单 | 现行 |
| [消息队列对接设计（RabbitMQ+aio-pika）.md](./消息队列对接设计（RabbitMQ+aio-pika）.md) | 异步任务、Outbox、重试与死信 | 现行 |
| [架构演进与Nacos-Higress集成规划.md](./架构演进与Nacos-Higress集成规划.md) | 配置中心 / 网关的演进规划 | **规划中**（未落地，勿当作现状） |
| [后端TODO清单.md](./后端TODO清单.md) | 未实现 / 占位项清单 | 现行 |

## 二、历史归档

以下文档描述的是**已下线的教育业务**（面试 / 考试 / 简历），仅作历史参考：

| 文档 | 说明 |
|---|---|
| [archive/多 Agent 系统架构设计方案.md](./archive/多%20Agent%20系统架构设计方案.md) | 早期四 Agent 架构（面试/考试/简历），已被三 Agent 取代 |
| [archive/前端页面接口对接现状与测试清单.md](./archive/前端页面接口对接现状与测试清单.md) | 早期页面与接口清单 |

## 三、现状基线（2026-11-16）

**业务 Agent**
- `qa`：知识库 RAG 问答（混合检索 + 精排 + 置信度判定 + Web 兜底 + 多轮摘要 + 长期记忆）
- `db_review`：待执行 SQL 的静态风险评审（四路并行预检 → 分级 → 建议 → 人工审批）
- `db_release`：已审批变更的沙箱验证与放行（输出 SQL，不执行生产）

**数据模型**
- 会话：`agent_thread`
- 轮次（唯一历史源）：`agent_unified_turn`
- 评测：`agent_qa_ragas_evals`（外键 `turn_id`，人工标准答案后触发）
- 检查点：`checkpoints / checkpoint_blobs / checkpoint_writes`（明确查询配置 schema）
- 已删除：`agent_qa_results`、`agent_run`、教育业务域表

**权限点**
```
unified:ask
unified_session:page / view / delete
unified_turn:page / view / review
unified_file:page / view / upload / download
+ 平台域 / 租户自管域 / 菜单域
```

**其他约定**
- 关键写库失败**不降级**，接口/SSE 返回 `code` + `msg`；
- 检索日志见 `rag.retrieve.done`（tenant / candidates / rerank_used / top_score / threshold / hit）；
- RAGAS 使用官方 `ragas.evaluate` + 官方 metrics，失败即 `failed`（不编造分数）。
