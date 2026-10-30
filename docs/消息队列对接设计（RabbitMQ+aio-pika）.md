# 消息队列对接设计（RabbitMQ + aio-pika）

> 范围：为 agent-platform 引入消息队列，承载**执行类异步任务**。本文只设计，不改动业务代码。
> RabbitMQ 作为项目**外独立中间件**部署（如 `E:\cywork\devsoft\ribbitmq`），不依赖多租户多智能体协作平台；多租户多智能体协作平台只消费它，连接串见 `BrokerSettings`。项目内 `docker/docker-compose.rabbitmq.yml` 仅作本地联调参考示例，非部署依据。

## 1. 目标与范围

引入 RabbitMQ 作为 broker，承载：

- 长任务 worker（多 Agent 串联 / 长推理）
- 知识库重索引（低置信度问答补充回流后向量化）
- 通知外发（邮件 / 企业微信 / 飞书 / Webhook / 工单）
- 审计批量落库（削峰）

**不交给消息队列**：HITL 人工挂起待办本身（留在 `agent_escalation` PG 表做状态机）；但其“教师确认后触发重索引 / 超时提醒”这类动作由消费端处理。

## 2. 为什么是 aio-pika，而不是 Celery / pika

- `pika` 是同步阻塞客户端，与多租户多智能体协作平台 asyncpg / `redis.asyncio` 的全程 async 栈冲突，不适合。
- `Celery` 自带 retry / beat / flower，但默认是同步进程模型，task 内调 async 代码需 `asyncio.run` 包裹、连接池要与 HTTP 进程隔离，框架偏重。
- `aio-pika` 基于 asyncio，原生协程，贴合现有栈；重试 / 定时 / 监控需自行实现，但量不大。

结论：纯 async 项目用 aio-pika 比 Celery 少一层摩擦，且 broker 仍是 RabbitMQ（成熟、持久化、DLX 完善）。

## 3. 依赖与配置

- `requirements.txt` 增加：`aio-pika`
- `backend/config/schemas.py` 增加分组（复用现有扁平 env 风格）：

```python
class BrokerSettings(BaseSettings):
    """RabbitMQ（消息队列 broker）。"""
    model_config = SettingsConfigDict(**_COMMON, env_prefix="RABBITMQ_")

    host: str = "localhost"
    port: int = 5672
    user: str = "agent"
    password: str = "agent_pass"
    vhost: str = "agent_platform"

    @property
    def url(self) -> str:
        from urllib.parse import quote, urlunparse
        netloc = f"{quote(self.user, safe='')}:{quote(self.password, safe='')}@{self.host}:{self.port}"
        return urlunparse(("amqp", netloc, f"/{self.vhost}", "", "", ""))
```

- broker 连接串：`amqp://agent:agent_pass@localhost:5672/agent_platform`

## 4. 部署

RabbitMQ 是**项目外独立部署的中间件**（如 `E:\cywork\devsoft\ribbitmq`），不在多租户多智能体协作平台仓库内，也不混入根目录的一站式 compose。项目侧只做两件事：

- 配置连接串：`BrokerSettings` 的 `RABBITMQ_*` 环境变量指向该独立实例（开发机通常为 `localhost:5672` / vhost `agent_platform`）；
- 在 aio-pika 客户端落实队列 durable、消息持久、手动 ack（见第 6 节）。

容器本身的磁盘持久化、数据卷、Management 界面由独立中间件部署负责；项目内 `docker/docker-compose.rabbitmq.yml` 仅作本地联调参考，实际以你独立部署的 RabbitMQ 为准。

## 5. 代码架构（贴合 AppServer manager 编排）

```
backend/
  broker/
    client.py     # aio-pika 连接单例（连接 / 通道）
    manager.py    # BrokerManager：挂 AppServer，建连 + 声明 + 启消费协程
    consumer.py   # 消费循环：按消息类型路由到 handler
    dlq.py        # 重试 / 死信参数（DLX / 队列参数）
  handlers/
    agent.py      # run_agent_task（长任务）、reindex_knowledge（重索引）
    notify.py     # send_notification
    audit.py      # flush_audit
```

- `BrokerManager`（新增到 AppServer，order 放在 Redis / PG 之后、FastAPI 之前）：
  - `start()`：建 aio-pika 连接 → 声明 exchange / 业务 queue / DLX / DLQ（均 durable，幂等）→ `asyncio.create_task(consume_loop())` 启动消费。
  - `stop()`：取消消费任务 → 关闭连接（同进程优雅停，比 Celery 的 `control.shutdown` 干净）。
- 生产者：在 service / dao 层 `await exchange.publish(Message(...), routing_key=...)` 即返回。
- 消费分发：`consume_loop` 按 `message.headers["type"]` 路由到 `handlers/*`；成功 `ack()`，失败 `nack(requeue=False)` 进 DLQ。

## 6. 消息可靠性与多租户隔离：持久化、手动 ack、幂等、事务、鉴权（重点）

RabbitMQ 的投递语义是 **at-least-once**（不丢，但可能重投）。要保证“不丢 + 不重复生效”，需从四个层面入手。这四项由**应用端**落实（broker 服务端由独立部署的 RabbitMQ 中间件负责进程与磁盘持久，无法强制客户端 ack 模式）。

### 6.1 持久化（不丢消息）

- **Broker 层**：磁盘节点 + 数据卷（`/var/lib/rabbitmq`），进程重启消息不丢；`rabbitmq:3.13-management` 默认即磁盘节点。
- **声明层**：exchange / queue / DLX / DLQ 均 `durable=True`（元数据持久化）。单节点用 classic 队列即可；多节点跨机部署用 **quorum 队列**（基于 Raft，多数派确认才返回，比 classic 队列 + 镜像更稳，需集群）。
- **消息层**：发布时 `Message(body, delivery_mode=2)`（持久消息，落盘）；`delivery_mode=1` 为瞬态，broker 重启即丢，禁用。
- **生产者确认（publisher confirm）**：开启 confirm 模式，等待 broker 回 ack 再认为发送成功；网络抖动 / broker 不可用时抛异常并重试，防止“发出去但没收到”的静默丢失。
- 持久化只保证 broker 不丢，不保证消费端一定处理成功——这靠 6.2 的手动 ack。

### 6.2 手动 ack（消费后提交）

- **`auto_ack=False`**（手动 ack）；并设 `prefetch_count=1` 做公平分发，防止一个 worker 积压。
- **成功**：业务处理完（含写库）后再 `await message.ack()`。**ack 必须在本地 DB 事务提交之后**，否则 DB 回滚但消息已确认，会丢处理。
- **失败**：`await message.nack(requeue=False)` → 进 DLX / DLQ；**不要 `requeue=True` 无限制重投**，避免死循环与队头阻塞。
- **禁止 `auto_ack=True`**：消费中进程崩溃会直接丢消息（broker 认为已送达）。
- **异常隔离**：`consume_loop` 单条消息处理要 `try/except`，失败只 nack，不能让异常拖垮整个消费协程。

### 6.3 消息幂等（不重复生效）

at-least-once 语义下，网络重投、消费者重启、DLX 重试都会让同一业务被消费多次。多租户多智能体协作平台**统一走 Outbox（§6.4）**，幂等由 outbox 状态机天然保证（无需额外 Redis 去重表）：

- **去重依据**：每条消息的 `message_id` 即 `agent_outbox.id`；消费端处理前查 `agent_outbox.status`：
  - 已是 `done` → 直接 `ack` 跳过（重投 / 死信重试不会重复生效）；
  - 正常处理 → 处理后标 `done`。
- 这覆盖了 at-least-once 的“重投去重”。生产侧“同业务重复触发”由业务层保证只写一次 outbox（或 payload 带业务唯一键）。
- 幂等是 at-least-once 下的**必须项**；Outbox 模式把幂等与投递状态合一，省去独立去重存储。

### 6.4 事务与最终一致性（Outbox 本地消息表）

RabbitMQ **不支持 XA / 两阶段提交**，broker 与 PostgreSQL 不能放在同一分布式事务。多租户多智能体协作平台用 **Outbox（本地消息表）** 模式解决“写库 + 发消息”的原子性：业务写 PG 与写 `agent_outbox(pending)` 同事务，独立投递协程扫 `pending` 发 MQ，broker 不可用时消息也不丢（留 outbox 补发）。

**表结构**（`agent_outbox`，与业务表同事务写入）：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | 消息唯一 id，同时作为 MQ `message_id` |
| topic | VARCHAR(64) | 消息 type / routing_key（如 `audit.flush`） |
| payload | JSONB | 完整消息体（含 `type`/`tenant_id`/`user_id`/`payload`） |
| status | VARCHAR(16) | `pending`(待投递) \| `sent`(已发 MQ) \| `done`(消费端已处理) \| `failed`(消费失败超限) |
| retry_count | INT | 投递 / 消费重试次数 |
| last_error | TEXT | 最近失败原因 |
| tenant_id | BIGINT | 冗余，便于排查 |
| sent_at | TIMESTAMPTZ | 投递到 MQ 的时间 |

死信落库表 `agent_dead_letter`（消费重试超限的任务）：`id` / `topic` / `payload` / `origin_queue` / `error` / `retry_count` / `tenant_id`。

**流程**：
1. 生产者调 `publish_task(...)` → 写 `agent_outbox(pending)` 即返回（不直接连 broker）；
2. `BrokerManager` 内的 `OutboxPublisher` 协程（每 5s）扫 `pending` → `client.publish(message_id=outbox.id)` → 标 `sent`；发失败 `retry_count++`，超 3 次标 `failed`；
3. 消费端处理成功 → 标 `done` + `ack`；失败 `retry_count++`，超限落 `agent_dead_letter` + 标 `failed` + `ack`，未超限 `nack` 进重试队列（见 §7）；
4. **“消费之后改状态”**：`done` 由消费端在处理成功后回写，正是幂等依据（§6.3）。

> 低风险的纯通知类也可直发，但统一走 Outbox 更简单一致、且 broker 不可用时不丢。

### 6.5 多租户隔离与消息鉴权

多租户多智能体协作平台是强租户隔离的多租户系统，消息消费端必须校验“谁发起、操作哪个租户”，防止越权（租户 A 的任务读写租户 B 数据，或普通用户触发超管动作）。broker 本身不做业务鉴权，鉴权在消费端落地。

- **消息携带身份**：每条消息的 body 必须带 `tenant_id`、`user_id`（发起者）；routing_key / topic 也建议带租户维度（如 `agent.run.{tenant_id}`），便于按租户分队列、隔离消费。超管发起的任务 `user_id` 可为 0，但 `tenant_id` 仍按目标租户填。
- **消费端鉴权（必做，零信任）**：handler 处理前按 `tenant_id` + `user_id` 重新走一遍权限校验，不直接信任消息内容：
  - 查用户角色 / scope，确认其对 `tenant_id` 有对应权限（如重索引需 `knowledge:write`、通知需 `notify:send`）；
  - 确认 `tenant_id` 在用户可见范围内（租户管理员仅本租户，超管跨租户）；
  - 校验不通过直接 `ack`（或进死信），**不执行**业务动作，避免越权写入。
- **租户数据边界**：handler 内所有 DB / Milvus 操作必须带 `tenant_id` 过滤，复用现有 DAO 的租户隔离逻辑，不能凭消息里的 id 直接查全表。
- **越权兜底**：即使生产者是可信服务，消费端也要以校验为准——消息可能被重投或（broker 未加鉴权时）被伪造。
- **审计**：消费端执行的关键动作仍走现有审计（谁、在哪个租户、做了什么），保持可追溯。
- 功能映射见第 8 节，每条消息均带 `tenant_id` / `user_id` 且消费端做上述鉴权。

## 7. 重试与死信（RabbitMQ 原生，不依赖框架）

默认 **3 次重试、重试队列 TTL 30s**（见 `broker/dlq.py` 的 `MAX_RETRIES` / `RETRY_TTL_MS`，可按需调）。

- 业务队列 `Q` 声明带 `x-dead-letter-exchange=agent.platform.retry`、`x-dead-letter-routing-key=Q`；
- 重试队列 `Q.retry` 带 `x-message-ttl=30000`、`x-dead-letter-exchange=agent.platform.dlx`、`x-dead-letter-routing-key=Q`；
- 消费失败 `nack(requeue=False)` → 进 `retry` exchange → `Q.retry`（延迟 30s）→ `dlx` exchange → 回 `Q` 重投；
- 重试计数存 `agent_outbox.retry_count`（按 `message_id` 查，不依赖消息头）；超限（≥3）由消费端落 `agent_dead_letter` 表 + 标 outbox `failed` + `ack`（已落表，不再入队）；
- 最终死信队列 `Q.dlq` 绑定 `agent.platform.dlx`，由 `consumer._on_dlq` 消费仅记录告警（主要落表已在业务消费端完成）；
- 死信可查 `agent_dead_letter` 表排查丢失 / 反复失败任务。

> 不依赖 `rabbitmq_delayed_message_exchange` 插件（独立实例大概率没装），用 TTL 队列 + DLX 中转实现延迟重试。

## 8. 功能 → 消息映射

| 功能 | routing_key / type | 处理 |
|---|---|---|
| 长任务 | `agent.run` | 执行多 Agent 串联，结果经回传桥推前端 |
| 重索引 | `knowledge.reindex` | 取补充内容 → 向量化 → 写 Milvus；按 kpq_id 幂等 |
| 通知 | `notify.send` | 邮件 / 企微 / Webhook；retry + 死信 |
| 审计 | `audit.flush` | 批量落库削峰 |
| HITL 超时 | （beat 定时扫 PG 表） | 替代定时轮询，发提醒 |

## 9. 结果回传桥（Redis Stream，必补）

当前 SSE 在 HTTP 连接内直推；worker 是独立消费协程 / 进程，跑完结果推不到持有 SSE 的 uvicorn worker。引入 MQ 后必须补一条回传通道：

- worker 处理完 `publish` 到 Redis Stream / 频道（key 带 `thread_id`）；
- 持有 SSE 的 uvicorn worker 订阅该频道，转发给前端。

否则长任务执行完前端收不到。

## 10. 定时任务（HITL 超时）

用 **asyncio 定时协程**（`SchedulerManager`，不引入 APScheduler 额外依赖，贴合全 async 栈；原设计写 APScheduler，等价替代）。`SchedulerManager` 随 AppServer 启动（与 broker 同启用），每 60s 扫 `agent_escalation` 表中 `status='pending'` 且 `create_at` 超过阈值（默认 30min，见 `ESCALATION_TIMEOUT_MIN`）且 `last_reminder_at IS NULL` 的项，经 `publish_task`（`notify.send`）发超时提醒，发后写 `last_reminder_at=now()` 避免重复提醒。提醒经 Outbox → MQ 由通知 handler 外发（执行逻辑待接入，见 §8/§11）。

## 11. 迁移路径（从 PG 表轮询 → RabbitMQ）

1. **阶段 1（已完成框架 + 审计落库）**：broker 接入、Outbox、消费端鉴权、审计真实落库；通知 handler 已鉴权 + 结构，外发渠道待接。
2. **阶段 2（待业务入口改造）**：知识库回流 / 通知 / 审计的**业务入口**改为调 `publish_task`（写 Outbox），替换原有同步写 / 轮询；Outbox + 投递协程已就绪。
3. **阶段 3（最难，待做）**：长任务 worker 执行 + 补 Redis Stream 回传桥（SSE 跨进程推送，见 §9）。
4. **阶段 4（已完成）**：HITL 超时提醒由 `SchedulerManager` 定时扫描 `agent_escalation` 发 `notify.send`（§10），替代扫表轮询。

## 12. 风险与注意

- 重试 / 死信 / 定时 / 监控需自行实现（量不大，但 Celery 是白送的）。
- **结果回传桥必补**，否则长任务结果丢失。
- 消费协程要 `try/except` 隔离，单个消息失败只 `nack`，不能拖垮 `consume_loop`。
- 幂等：消费端按 `kpq_id` / `thread_id` 做 `SETNX`（Redis）或 PG 唯一约束去重，防重复消费。
- 连接数：worker 与 HTTP 进程各自建池，注意 PG / Milvus 总连接数。
