"""统一咨询入口一期提示词常量（D18）。

一期所有新增提示词以模块级 str 常量落地，运行时不读配置中心；常量即唯一来源。
模板变量一律用具名 str.format() 占位（如 {capabilities}），不 eval / 不 f-string 拼用户输入；
用户输入经 check_input() 后进入。二期接 Nacos 时只替换本模块取值实现，调用方零改动。
"""
from __future__ import annotations

ROUTE_SYSTEM_PROMPT: str = """你是一个咨询入口的路由分类器。根据用户消息与可见的 Agent 能力，判断应由哪个 Agent 承接。

# 输出要求
只输出一个 JSON 对象，结构如下（合法 JSON，键名带引号）：
{{
  "label": "命中 Agent 的标识",
  "reason": "一句话分类依据",
  "confidence": 0.0~1.0 的浮点数,
  "init_values": {{ "target_position": "", "exam_id": "", "resume_review_id": "" }}
}}
未命中任何 Agent 时，label 设为 "general"，init_values 留空。

# 可选 Agent 列表
{agent_list}
"""

ROUTE_TURN_TEMPLATE: str = """【最近对话】
{history}

【用户当前输入】
{user_input}
"""

RULE_REPLY_GREETING: str = (
    "你好，我是咨询助手。你可以直接描述问题，或选择下方卡片进入对应的专业 Agent。"
)
RULE_REPLY_THANKS: str = "不客气，随时可以继续提问。"
RULE_REPLY_BYE: str = "好的，再见。如果还有问题，随时回来。"
RULE_REPLY_IDENTITY: str = (
    "我是多智能体咨询入口，负责把你的请求分派给合适的专业 Agent"
    "（如问答、面试、考试、简历）。"
)
RULE_REPLY_CAPABILITY: str = "当前可用的能力如下：\n{capabilities}"

DYNAMIC_CAPABILITY_ITEM: str = "- {display_name}：{description}（输入示例：{example}）"

CLARIFY_TEMPLATE: str = """还需要补充一些信息才能开始：
{missing_fields}
请直接回复对应内容，我会自动继续。"""

SUMMARY_COMPRESS_PROMPT: str = """请将以下对话压缩为一段简洁的摘要，保留关键事实、用户背景、已完成的步骤与未决问题。不要新增未提及的信息。

【已有摘要】
{existing_summary}

【本轮对话】
{messages}
"""

LONG_MEMORY_EXTRACT_PROMPT: str = """从下面的会话摘要中抽取跨会话可用的长期记忆，按类型归类。
允许的类型：summary（用户概况/历史摘要）、fact（具体事实）、preference（偏好）。
只输出 JSON 数组，每项包含 block 与 content 两个字段。

【会话摘要】
{summary}
"""

PIPELINE_PLAN_PROMPT: str = """根据用户目标，规划一组 Agent 串联执行步骤。每个步骤指定 agent_type 与说明。
只输出 JSON（合法 JSON，键名带引号）：
{{
  "title": "",
  "intro": "",
  "steps": [ {{ "step": "1", "agent_type": "", "label": "", "desc": "", "route_key": "", "tip": "" }} ]
}}

【可用 Agent】
{agent_list}

【用户目标】
{goal}
"""

TASK_GUIDANCE_TEMPLATE: str = """已为你创建任务：{artifact_type}。
{action_label}
"""
