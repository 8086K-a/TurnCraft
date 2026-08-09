"""路由 golden set：话术 → 期望的轨道/工具/决策。

用途：
- tests/eval/run_eval.py 用真实 LLM + 千问 embedding 跑，评估准确率；
- tests/test_golden_code_path.py 用确定性 FakeLlm 跑，验证代码路径。
"""
import json

# expected: task / knowledge / chitchat / clarify / low
GOLDEN_CASES = [
    # ---- 执行类 ----
    {
        "text": "我要退款",
        "llm_calls": [{"tool": "refund_request", "parameters": {}}],
        "expected": "task",
        "flow": "refund_request",
    },
    {
        "text": "帮我退一下 ORD1 这个订单",
        "llm_calls": [{"tool": "refund_request", "parameters": {"order_number": "ORD1"}}],
        "expected": "task",
        "flow": "refund_request",
    },
    {
        "text": "我要投诉，视频看不了",
        "llm_calls": [{"tool": "ticket_submission", "parameters": {"ticket_description": "视频看不了"}}],
        "expected": "task",
        "flow": "ticket_submission",
    },
    {
        "text": "转人工",
        "llm_calls": [],
        "expected": "task",
        "flow": "human_handoff",
    },
    # ---- 查询类 ----
    {
        "text": "查订单 ORD1",
        "llm_calls": [{"tool": "order_status_query", "parameters": {"order_number": "ORD1"}}],
        "expected": "task",
        "flow": "order_status_query",
    },
    {
        "text": "我的订单现在什么状态",
        "llm_calls": [{"tool": "order_status_query", "parameters": {}}],
        "expected": "task",
        "flow": "order_status_query",
    },
    {
        "text": "Python全栈课程怎么样",
        "llm_calls": [{"tool": "course_consultation", "parameters": {"course_name": "Python全栈"}}],
        "expected": "task",
        "flow": "course_consultation",
    },
    {
        "text": "课程价格是多少",
        "llm_calls": [{"tool": "course_consultation", "parameters": {}}],
        "expected": "task",
        "flow": "course_consultation",
    },
    {
        "text": "我的学习进度怎么样",
        "llm_calls": [{"tool": "learning_progress_query", "parameters": {}}],
        "expected": "task",
        "flow": "learning_progress_query",
    },
    # ---- 知识类 ----
    {
        "text": "课程咨询",
        "llm_calls": [{"tool": "kb_course", "parameters": {}}],
        "expected": "knowledge",
        "intent": "课程咨询",
    },
    {
        "text": "想了解下你们有哪些课程",
        "llm_calls": [{"tool": "kb_course", "parameters": {}}],
        "expected": "knowledge",
        "intent": "课程咨询",
    },
    {
        "text": "退款政策是什么",
        "llm_calls": [{"tool": "kb_refund_policy", "parameters": {}}],
        "expected": "knowledge",
        "intent": "退款政策",
    },
    {
        "text": "怎么报名",
        "llm_calls": [],
        "expected": "knowledge",
        "intent": "报名流程",
    },
    {
        "text": "怎么申请退款",
        "llm_calls": [],
        "expected": "knowledge",
        "intent": "退款政策",
    },
    # ---- 闲聊 / 兜底 ----
    {
        "text": "你好",
        "llm_calls": [],
        "expected": "chitchat",
    },
    {
        "text": "帮我订个机票",
        "llm_calls": [],
        "expected": "chitchat",
    },
    # ---- 多意图澄清 ----
    {
        "text": "我要退款顺便查下订单",
        "llm_calls": [
            {"tool": "refund_request", "parameters": {}},
            {"tool": "order_status_query", "parameters": {}},
        ],
        "expected": "clarify",
    },
]


def llm_responses_by_text() -> dict[str, str]:
    return {
        case["text"]: json.dumps({"tool_calls": case["llm_calls"]}, ensure_ascii=False)
        for case in GOLDEN_CASES
    }


def judge(plan, case) -> tuple[bool, str]:
    expected = case["expected"]
    if expected == "clarify":
        return (plan.clarify == "multiple_intents", "clarify=multiple_intents")
    if expected == "chitchat":
        return (plan.chitchat == {} and plan.task is None and plan.knowledge is None, "chitchat")
    if expected == "knowledge":
        intent = case.get("intent")
        ok = plan.knowledge is not None and intent in plan.knowledge.get("intents", [])
        return (ok, f"knowledge intent={intent}")
    if expected == "task":
        flow = case.get("flow")
        commands = plan.task.commands if plan.task else []
        ok = any(
            (c.get("command") == "start_flow" or c.get("command") == "resume_flow")
            and c.get("flow") == flow
            for c in commands
        )
        return (ok, f"task flow={flow}")
    if expected == "low":
        return (plan.task is None and plan.knowledge is None and plan.chitchat == {}, "low")
    return (False, f"unknown expected={expected}")
