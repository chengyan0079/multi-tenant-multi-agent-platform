"""消息队列基础设施常量：exchange / DLX / 业务队列（含重试与最终死信）。

topic 交换：routing_key 与队列同名。
重试链路（见 docs/消息队列对接设计 §7）：
- 业务队列 Q 消费失败 → nack 进 RETRY_DLX（routing_key=Q）→ 重试队列 Q.retry
  （TTL 延迟）→ FINAL_DLX（routing_key=Q）→ Q 重投；
- 重试超限 → 消费端落 agent_dead_letter 表 + 标 outbox failed，原消息 ack（已落表，不进队列）。
"""
from __future__ import annotations

EXCHANGE = "agent.platform"
RETRY_DLX = "agent.platform.retry"   # 失败先去这里，路由到 .retry 队列延迟重投
FINAL_DLX = "agent.platform.dlx"     # 超过重试次数最终死信（预留通道）

RETRY_TTL_MS = 30000   # 重试队列延迟（毫秒，可按需调）
MAX_RETRIES = 3        # 重试上限（与投递共用，可按需调）

# 业务队列（routing_key 与队列同名）
QUEUES: tuple[str, ...] = (
    "agent.run",  # 长任务（多 Agent 串联 / 长推理）
    "knowledge.reindex",  # 知识库重索引（低置信问答补充回流）
    "notify.send",  # 通知外发（邮件 / 企微 / Webhook / 工单）
    "audit.flush",  # 审计批量落库
)

# 最终死信队列（每个业务队列一个 .dlq，绑定 FINAL_DLX，routing_key=队列名）
DLQ_QUEUES: tuple[str, ...] = tuple(f"{q}.dlq" for q in QUEUES)
