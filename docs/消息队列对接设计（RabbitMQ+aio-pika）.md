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
    types.py             # TaskType 枚举：消息类型的唯一来源
    envelope.py          # 消息信封：key / type / header / data + 格式校验
    topology.py          # 拓扑唯一定义：交换机、QueueSpec、重试与死信链路、声明
    routing.py           # 消息类型 → 投递目标（业务 / 广播的唯一分流点）
    publish.py           # 入队入口：只写 Outbox（enqueue_task / publish_config_refresh）
    outbox_publisher.py  # 扫 Outbox 投递协程
    security.py          # 消费端零信任鉴权
    consumer/
      __init__.py        # 消费装配：按拓扑分三组（业务 / 死信 / 广播）
      strategies.py      # 三类消费策略（任务 / 广播 / 死信）
    handlers/            # 各业务类型处理函数 + HANDLERS 注册表
  data/clients/broker.py             # aio-pika 客户端（连接 / 发布 / 消费原语）
  server/managers/broker_manager.py  # BrokerManager：启停与健康检查
  services/                          # 业务实现入口（handler 背后的真实逻辑）
    agent_run.py                     # 长任务执行（TODO）
    indexing.py                      # 文档解析 / 知识回流（TODO）
    notification.py                  # 通知渠道注册表 + 分发
```

handler 只做三件事：鉴权、从 `data` 取参数、调 `services/` 并让异常上抛。业务实现全部落在 `services/`，补齐时不需要再改 handler。

- `BrokerManager`（AppServer 中 order=20）：
  - `start()`：建连接 → `topology.declare_all()` → `consumer.start_consumers()` → 启动 Outbox 投递协程。
  - `stop()`：停投递协程 → 取消消费协程 → 关闭连接。
  - 任一环节抛错即启动失败（fail-fast），不会带着半套拓扑继续运行。
- 生产者：业务侧只调 `enqueue_task(TaskType.XXX, ...)` 写 Outbox，不直接操作 broker。
- 消费分发：`strategies` 先做信封校验，再按 `type` 查 `HANDLERS` 分发；成功 `ack`，失败走重试链路（§7）。

### 5.1 消息信封（key / type / header / data）

所有消息统一四段式，JSON 编码：

```json
{
  "key": "01a1a678-903f-763a-85ec-fd603b45c6a3",
  "type": "qa.parse",
  "header": {
    "version": 1,
    "tenant_id": 1,
    "user_id": 2,
    "trace_id": "9f2c...",
    "issued_at": 1730700000.123,
    "retry_count": 0
  },
  "data": {"file_id": 12, "object_key": "tenant/1/a.pdf"}
}
```

| 字段 | 作用 | 消费端怎么用 |
|---|---|---|
| `key` | 幂等键，等于 `agent_outbox.id` | 查 `status='done'` 则跳过 |
| `type` | `TaskType` 枚举值 | 决定路由与 handler 分发 |
| `header.version` | 信封结构版本 | 不等于当前版本直接拒绝 |
| `header.tenant_id` / `user_id` | 发起者身份 | 零信任重做鉴权（§6.5） |
| `header.trace_id` | 链路追踪 | 透传到日志，不参与业务判断 |
| `header.issued_at` | 入队时间 | 只用于排查延迟 |
| `header.retry_count` | 重试次数 | 消费端回写 Outbox |
| `data` | 业务数据 | handler 唯一读取的内容 |

设计取舍：

- **幂等键与业务数据分离**：`key` 只负责"这条消息是否处理过"，业务幂等键（如 `review_id`、`file_id`）仍由 handler 自己判断，两者不混用。
- **身份放 header 而不是顶层**：业务数据与元数据边界清晰，`data` 可以整块交给 handler。
- **不做旧格式兼容**：切换时队列为空，直接一次性替换，不留双解析分支。
- **信封校验前置**：结构、版本、类型三项由 `TaskMessage.from_json` 统一校验，失败按毒消息直接 ack 丢弃。

### 5.2 类型枚举（TaskType）

`backend/broker/types.py` 定义全部消息类型，枚举值同时是队列名、`HANDLERS` 键与 Outbox `topic`：

| 枚举 | 值 | 队列 prefetch |
|---|---|---|
| `AGENT_RUN` | `agent.run` | 1 |
| `QA_PARSE` | `qa.parse` | 2 |
| `QA_RAGAS_REVIEW` | `qa.ragas_review` | 1 |
| `RESUME_REVIEW` | `resume.review` | 1 |
| `EXAM_REVIEW` | `exam.review` | 1 |
| `NOTIFY_SEND` | `notify.send` | 10 |
| `AUDIT_FLUSH` | `audit.flush` | 20 |

> `CONFIG_REFRESH` 已移出消息队列：跨副本配置刷新改用 Redis 版本号拉取（见 §8），
> 故当前 `BROADCAST_TYPES` 为空；FANOUT 广播交换机 / `on_broadcast` 策略作为基础设施保留，暂无业务使用。

命名约定 `域.动作`（全小写、点分隔）。用枚举而不是字符串 + 运行时正则，是因为拼写错误在编码期就会被类型系统拦住；启动期 `topology.validate_handler_coverage()` 再校验"枚举 / 队列 / handler"三者一致，缺一侧直接启动失败。

新增一类消息三步：加枚举值 → 在 `TASK_QUEUES`（或 `BROADCAST_TYPES`）加声明 → 在 `HANDLERS` 注册处理函数。

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

- **去重依据**：每条消息信封里的 `key` 即 `agent_outbox.id`；消费端处理前查 `agent_outbox.status`：
  - 已是 `done` 或 `failed` → 直接 `ack` 跳过（重投 / 死信重试不会重复生效）；
  - 正常处理 → 处理后标 `done`。
  - 需要人工重跑失败消息时，应先把 outbox 状态重置为 `pending`（或换新 key），否则会被终态幂等跳过。
- 这覆盖了 at-least-once 的“重投去重”。生产侧“同业务重复触发”由业务层保证只写一次 outbox（或 payload 带业务唯一键）。
- 幂等是 at-least-once 下的**必须项**；Outbox 模式把幂等与投递状态合一，省去独立去重存储。

### 6.4 事务与最终一致性（Outbox 本地消息表）

RabbitMQ **不支持 XA / 两阶段提交**，broker 与 PostgreSQL 不能放在同一分布式事务。多租户多智能体协作平台用 **Outbox（本地消息表）** 模式解决“写库 + 发消息”的原子性：业务写 PG 与写 `agent_outbox(pending)` 同事务，独立投递协程扫 `pending` 发 MQ，broker 不可用时消息也不丢（留 outbox 补发）。

**表结构**（`agent_outbox`，与业务表同事务写入）：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | 消息唯一 id，由应用生成，等于信封 `key` 与 MQ `message_id` |
| topic | VARCHAR(64) | 消息 type（枚举值，如 `audit.flush`） |
| payload | JSONB | 四段式信封（`key` / `type` / `header` / `data`），见 §5.1 |
| status | VARCHAR(16) | `pending`(待投递) \| `sent`(已发 MQ) \| `done`(消费端已处理) \| `failed`(消费失败超限) |
| retry_count | INT | 投递 / 消费重试次数 |
| last_error | TEXT | 最近失败原因 |
| tenant_id | BIGINT | 冗余，便于排查 |
| sent_at | TIMESTAMPTZ | 投递到 MQ 的时间 |

死信落库表 `agent_dead_letter`（消费重试超限的任务）：`id` / `topic` / `payload` / `origin_queue` / `error` / `retry_count` / `tenant_id`。

**流程**：
1. 生产者调 `enqueue_task(...)` → 写 `agent_outbox(pending)` 即返回（不直接连 broker）；
2. `BrokerManager` 内的 `OutboxPublisher` 协程（每 5s）扫 `pending` → `client.publish(message_id=outbox.id)` → 标 `sent`；发失败 `retry_count++`，超 3 次标 `failed`；
3. 消费端处理成功 → 标 `done` + `ack`；失败 `retry_count++`，超限落 `agent_dead_letter` + 标 `failed` + `ack`，未超限 `nack` 进重试队列（见 §7）；
4. **“消费之后改状态”**：`done` 由消费端在处理成功后回写，正是幂等依据（§6.3）。

> 低风险的纯通知类也可直发，但统一走 Outbox 更简单一致、且 broker 不可用时不丢。

### 6.5 多租户隔离与消息鉴权

多租户多智能体协作平台是强租户隔离的多租户系统，消息消费端必须校验“谁发起、操作哪个租户”，防止越权（租户 A 的任务读写租户 B 数据，或普通用户触发超管动作）。broker 本身不做业务鉴权，鉴权在消费端落地。

- **消息携带身份**：每条消息的 `header` 必须带 `tenant_id`、`user_id`（发起者），见 §5.1；当前不做按租户分队列，租户隔离靠消费端鉴权与 DAO 的 `tenant_id` 过滤（队列数量随租户线性增长，得不偿失）。超管发起的任务 `user_id` 可为 0，但 `tenant_id` 仍按目标租户填。
- **消费端鉴权（必做，零信任）**：handler 处理前按 `tenant_id` + `user_id` 重新走一遍权限校验，不直接信任消息内容：
  - 查用户角色 / scope，确认其对 `tenant_id` 有对应权限（如重索引需 `knowledge:write`、通知需 `notify:send`）；
  - 确认 `tenant_id` 在用户可见范围内（租户管理员仅本租户，超管跨租户）；
  - 校验不通过直接 `ack`（或进死信），**不执行**业务动作，避免越权写入。
- **租户数据边界**：handler 内所有 DB / Milvus 操作必须带 `tenant_id` 过滤，复用现有 DAO 的租户隔离逻辑，不能凭消息里的 id 直接查全表。
- **越权兜底**：即使生产者是可信服务，消费端也要以校验为准——消息可能被重投或（broker 未加鉴权时）被伪造。
- **审计**：消费端执行的关键动作仍走现有审计（谁、在哪个租户、做了什么），保持可追溯。
- 功能映射见第 8 节，每条消息均带 `tenant_id` / `user_id` 且消费端做上述鉴权。

## 7. 重试与死信（RabbitMQ 原生，不依赖框架）

默认 **3 次重试、重试队列 TTL 30s**（见 `broker/topology.py` 的 `MAX_RETRIES` / `RETRY_TTL_MS`，可按需调）。

- 业务队列 `Q` 声明带 `x-dead-letter-exchange=agent.platform.retry`、`x-dead-letter-routing-key=Q`；
- 重试队列 `Q.retry` 带 `x-message-ttl=30000`、`x-dead-letter-exchange=agent.platform.dlx`、`x-dead-letter-routing-key=Q`；
- 消费失败 `nack(requeue=False)` → 进 `retry` exchange → `Q.retry`（延迟 30s）→ `dlx` exchange → 回 `Q` 重投；
- 重试计数存 `agent_outbox.retry_count`（按 `message_id` 查，不依赖消息头）；超限（≥3）由消费端落 `agent_dead_letter` 表 + 标 outbox `failed` + `ack`（已落表，不再入队）；
- 最终死信队列 `Q.dlq` 绑定 `agent.platform.dlx`，由 `consumer._on_dlq` 消费仅记录告警（主要落表已在业务消费端完成）；
- 死信可查 `agent_dead_letter` 表排查丢失 / 反复失败任务。

> 不依赖 `rabbitmq_delayed_message_exchange` 插件（独立实例大概率没装），用 TTL 队列 + DLX 中转实现延迟重试。

## 8. 功能 → 消息映射

| 功能 | type（TaskType） | 处理 |
|---|---|---|
| qa 知识库文档解析 | `QA_PARSE` / `qa.parse` | `backend/rag` 自研闭环：MinIO 字节 → 解析（含扫描件 OCR）→ **父子片两阶段切分** → 子片 BGE-M3 向量化写 Milvus（父片全文冗余在子片行）→ 回写 `parse_status` |
| QA 测评（RAGAS） | `QA_RAGAS_REVIEW` / `qa.ragas_review` | 异步跑 ragas 官方指标（`evaluate` + 官方 metrics），回填 `agent_qa_ragas_evals`；人工标准答案缺失直接 `failed` |
| 通知 | `NOTIFY_SEND` / `notify.send` | 邮件 / 企微 / Webhook；retry + 死信（外发渠道仍待实现） |
| 审计 | `AUDIT_FLUSH` / `audit.flush` | handler 存在，当前无生产端 |
| 长任务（历史） | `AGENT_RUN` / `agent.run` | **已清理**：统一咨询改为同步流式（SSE），不再经异步任务 |
| 简历评审 / 考试批改（历史） | `RESUME_REVIEW` / `EXAM_REVIEW` | **已下线**（教育业务域整体移除） |
| HITL 超时提醒 | — | 未实现：审批由 `interrupt` 承载，超时提醒策略待定 |

**跨副本配置刷新（不走 MQ）**：`AgentRegistry` / `LLMFactory` / `PluginRegistry` 是各副本的进程内缓存，
超管改配置后只有处理请求的副本刷新了内存。现由 `backend/services/config_refresh.py` 承担：
变更方对 `agent:config:refresh:{target}` 三个独立 key 执行 `INCR` 写版本号（DB 仍是权威源，Redis 只放信号）；
每个副本由 `SchedulerManager` 的 `config_refresh_poll` job（默认 5s）`MGET` 比对本地版本号，
仅对变化的 target 调用 reload。Redis 不可用时退化为定时全量 reload。
`publish_config_refresh(*targets)` 保留原签名委托该 service，管理端调用点无需改动。

**`agent_outbox.message_kind`**：记录投递语义，`task`（工作队列/竞争消费）/ `broadcast`（发布订阅/每副本一份），
值在 `enqueue_task` 中由 `routing.route(type).kind` 自动推导，调用方不传、不硬编码。
当前业务消息全为 `task`，`broadcast` 作为预留值保留。

## 9. 结果回传桥（Redis Stream，必补）

当前 SSE 在 HTTP 连接内直推；worker 是独立消费协程 / 进程，跑完结果推不到持有 SSE 的 uvicorn worker。引入 MQ 后必须补一条回传通道：

- worker 处理完 `publish` 到 Redis Stream / 频道（key 带 `thread_id`）；
- 持有 SSE 的 uvicorn worker 订阅该频道，转发给前端。

否则长任务执行完前端收不到。

## 10. 定时任务（HITL 超时）

用 **asyncio 定时协程**（`SchedulerManager`，不引入 APScheduler 额外依赖，贴合全 async 栈；原设计写 APScheduler，等价替代）。`SchedulerManager` 随 AppServer 启动（与 broker 同启用），每 60s 扫 `agent_escalation` 表中 `status='pending'` 且 `create_at` 超过阈值（默认 30min，见 `ESCALATION_TIMEOUT_MIN`）且 `last_reminder_at IS NULL` 的项，经 `enqueue_task`（`notify.send`）发超时提醒，发后写 `last_reminder_at=now()` 避免重复提醒。提醒经 Outbox → MQ 由通知 handler 外发（执行逻辑待接入，见 §8/§11）。

## 11. 迁移路径（从 PG 表轮询 → RabbitMQ）

1. **阶段 1（已完成框架 + 审计落库）**：broker 接入、Outbox、消费端鉴权、审计真实落库；通知 handler 已鉴权 + 结构，外发渠道待接。
2. **阶段 2（待业务入口改造）**：知识库回流 / 通知 / 审计的**业务入口**改为调 `enqueue_task`（写 Outbox），替换原有同步写 / 轮询；Outbox + 投递协程已就绪。
3. **阶段 3（最难，待做）**：长任务 worker 执行 + 补 Redis Stream 回传桥（SSE 跨进程推送，见 §9）。
4. **阶段 4（已完成）**：HITL 超时提醒由 `SchedulerManager` 定时扫描 `agent_escalation` 发 `notify.send`（§10），替代扫表轮询。

## 12. 风险与注意

- 重试 / 死信 / 定时 / 监控需自行实现（量不大，但 Celery 是白送的）。
- **结果回传桥必补**，否则长任务结果丢失。
- 消费协程要 `try/except` 隔离，单个消息失败只 `nack`，不能拖垮消费循环。
- 幂等：消息级由信封 `key` + `agent_outbox.status` 保证（§6.3）；业务级（同一业务对象被重复触发）仍需 handler 自己判断，如 `resume.review` 检查状态非 `processing`、`qa.parse` 检查 `parse_status`。
- 连接数：worker 与 HTTP 进程各自建池，注意 PG / Milvus 总连接数。

## 13. demo 与验证

`demo/mq/` 下按交换机与拓扑模式各提供一个可独立运行的脚本，连真实 RabbitMQ + PostgreSQL，自带断言，全部通过时退出码为 0：

| 脚本 | 覆盖内容 |
|---|---|
| `common.py` | 连接、`demo.` 前缀隔离、断言与清理 |
| `01_simple_queue.py` | 默认交换机 + 简单队列，FIFO |
| `02_work_queue.py` | 工作队列，两消费者各自 prefetch=1 时近似均分 |
| `03_fanout_pubsub.py` | fanout 广播到所有绑定队列，routing_key 被忽略 |
| `04_direct_routing.py` | direct 精确匹配，未匹配消息被丢弃 |
| `05_topic_routing.py` | topic 的 `*` 与 `#` 匹配差异 |
| `06_headers_exchange.py` | headers 的 `x-match=all` / `any` |
| `07_rpc.py` | reply_to + correlation_id 的请求响应 |
| `08_delay_dlq.py` | TTL + DLX 延迟重投、`nack(requeue=False)` 进死信 |
| `09_priority_queue.py` | `x-max-priority` 插队，同级仍 FIFO |
| `10_project_topology.py` | 项目真实拓扑端到端 |

运行方式：

```bash
python demo/mq/run_all.py           # 依次运行并汇总
python demo/mq/03_fanout_pubsub.py  # 单独运行某个
```

约定：

- 所有 demo 资源统一 `demo.` 前缀，运行结束在 `finally` 中删除，不影响 `agent.*` 真实拓扑；
- 连接串可用 `MQ_DEMO_URL` 覆盖，默认 `amqp://agent:agent@127.0.0.1:5672/agent_platform`；
- 队列不使用 `auto_delete`：`basic.qos` 与 consume 取消会触发自动删除，导致同一队列无法二次消费，统一改为显式删除。

`10_project_topology.py` 验证的完整链路：

1. `declare_all()` 在真实 broker 上声明 19 个队列（6 业务 + 6 retry + 6 dlq + 1 广播）；
2. `enqueue_task(TaskType.NOTIFY_SEND, ...)` 写 Outbox，断言 `payload` 是四段式信封；
3. `run_publisher()` 扫表投递到业务交换机，状态变 `sent`；
4. 探测队列收到消息，断言 `key` 与 Outbox 主键一致、`type` 解析为枚举、`header` 与 `data` 各就各位；
5. `on_task()` 消费（幂等判断 + handler + `mark_done`），状态变 `done`。

用一条绑定相同 routing_key 的临时探测队列接收消息，避免抢占业务队列里的其它消息；业务队列那份消息后续被真实消费者按幂等跳过。

最近一次执行：10 个脚本全部通过，`10_project_topology.py` 13/13 项断言通过。

## 14. 遗留项

| 项 | 现状 | 建议 |
|---|---|---|
| ~~配置刷新去重~~ | **已解决**：配置刷新不再走 MQ，改由 `services/config_refresh.py` 用 Redis 单调版本号 + 定时拉取，各副本按需 reload；晚启动副本天然自愈 | — |
| Outbox 重复投递 | 多副本时每个副本的投递协程都会扫到同一批 `pending`；广播消息已移出 Outbox，业务消息仍靠下游幂等兜住，属于"能对但浪费" | 投递侧用 `SELECT ... FOR UPDATE SKIP LOCKED` 抢占后再发 |
| 重试无退避 | `RETRY_TTL_MS` 固定 30s，三次重试间隔相同 | 按退避档位拆多个 `.retry` 队列，或引入延迟消息插件 |
| Quorum 队列 | 业务队列为 classic 队列 | 多节点部署时换 `x-queue-type=quorum`，避免网络分区下双消费 |
| 业务幂等键 | `key` 仅保证消息级幂等，业务重复提交仍需 handler 自行判断 | 若要统一，给 Outbox 加 `message_key` 唯一索引，入队即冲突 |
| 信封签名 | `header` 未做 HMAC 防篡改 | 跨团队共用 broker 时再加 |
| 业务实现未接入 | `qa.parse`、`resume.review`、`exam.review`、`qa.ragas_review` 已接通；`agent.run` / `notify.send` / `audit.flush` 仍是 TODO 或暂无生产端 | 按 `services/` 内 TODO 顺序补齐 |
