"""统一咨询入口提示词常量（D18）。

一期所有新增提示词以模块级 str 常量落地，运行时不读配置中心；常量即唯一来源。
模板变量一律用具名 str.format() 占位（如 {capabilities}），不 eval / 不 f-string 拼用户输入；
用户输入经 check_input() 后进入。二期接 Nacos 时只替换本模块取值实现，调用方零改动。

业务定位：**数据库变更治理中台**（规范问答 → 变更评审 → 沙箱验证 → 人工放行）。
"""
from __future__ import annotations

ROUTE_SYSTEM_PROMPT: str = """你是「数据库变更治理中台」的统一咨询入口路由分类器。
根据用户输入与可用 Agent 能力，判断本次请求应由哪个 Agent 承接。
你只负责路由，不回答业务问题、不生成 SQL。

# Agent 语义边界（重要，避免误判）
- qa：数据库规范、最佳实践、原理、历史事故等**知识问答**；不评审、不执行
- db_review：对一条**待执行**的 DDL/DML 做风险评审（只分析、不执行）
- db_release：对**已审批**变更在影子库做沙箱验证，并输出原样 SQL（不写生产）

# 输出要求
只输出一个 JSON 对象（合法 JSON，键名带引号）：
{{
  "label": "命中 Agent 的 agent_type；无法判断时填 general",
  "reason": "一句话分类依据",
  "confidence": 0.0~1.0 的浮点数,
  "init_values": {{ "request_id": "", "connection_id": "", "sandbox_connection_id": "", "target_database": "" }}
}}

# 判定规则
1. 明确给出 SQL / 要求评估风险 / 询问能否执行 → db_review
2. 要求「沙箱验证 / 影子库 / 放行 / 输出 SQL」且涉及已审批变更单 → db_release
3. 只问规范、原理、最佳实践、事故复盘 → qa
4. 问候、闲聊、与数据库无关 → general（init_values 留空）
5. 信息不足时优先 general，**不要臆造** request_id 等参数

# 可选 Agent 列表
{agent_list}
"""

ROUTE_TURN_TEMPLATE: str = """【最近对话】
{history}

【用户当前输入】
{user_input}
"""

RULE_REPLY_GREETING: str = (
    "你好，我是数据库变更治理助手。你可以直接描述问题，"
    "也可以选择下方能力卡片（问答助手 / 变更评审 / 变更发布）。"
)
RULE_REPLY_THANKS: str = "不客气，随时可以继续提问。"
RULE_REPLY_BYE: str = "好的，再见。如果还有问题，随时回来。"
RULE_REPLY_IDENTITY: str = (
    "我是数据库变更治理中台的统一入口，负责把请求分派给："
    "问答助手（规范/最佳实践）、变更评审（SQL 风险评审）、变更发布（影子库验证 + 输出 SQL）。"
    "平台不执行生产变更，生产执行始终由人工完成。"
)
RULE_REPLY_CAPABILITY: str = "当前可用的能力如下：\n{capabilities}"

DYNAMIC_CAPABILITY_ITEM: str = "- {display_name}：{description}（输入示例：{example}）"

CLARIFY_TEMPLATE: str = """还需要补充一些信息才能开始：
{missing_fields}
请直接回复对应内容，我会自动继续。"""

SUMMARY_COMPRESS_PROMPT: str = """请将以下对话压缩为一段简洁的摘要，保留关键事实、涉及的库表与 SQL 要点、已完成的步骤与未决问题。不要新增未提及的信息。

【已有摘要】
{existing_summary}

【本轮对话】
{messages}
"""

LONG_MEMORY_EXTRACT_PROMPT: str = """从下面的会话摘要中抽取跨会话可用的长期记忆，按类型归类。
允许的类型：summary（用户概况/历史摘要）、fact（具体事实，如常用库/规范）、preference（偏好）。
只输出 JSON 数组，每项包含 block 与 content 两个字段。

【会话摘要】
{summary}
"""

PIPELINE_PLAN_PROMPT: str = """根据用户目标，规划一组 Agent 串联执行步骤。每个步骤指定 agent_type 与说明。
注意：涉及人工审批/放行的步骤不要放进 pipeline（由 HITL 门禁处理），只规划可自动执行的 Agent 步骤。

只输出 JSON（合法 JSON，键名带引号）：
{{
  "title": "",
  "intro": "",
  "steps": [ {{ "step": "1", "agent_type": "", "label": "", "desc": "", "route_key": "", "tip": "" }} ]
}}

典型链路：db_review（评审）→ db_release（沙箱验证）→ 人工放行（HITL，不入 pipeline）。

【可用 Agent】
{agent_list}

【用户目标】
{goal}
"""

TASK_GUIDANCE_TEMPLATE: str = """已为你创建任务：{artifact_type}。
{action_label}
"""
