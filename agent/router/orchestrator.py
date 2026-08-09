"""编排与适配层。

- RoutingOrchestrator：代码级确定性规则（取消/闲聊/指南/槽位补充）+ 判决（四态）。
  这些业务规则从旧的 turn_plan.jinja2 prompt 搬进代码——"LLM 只做理解，代码做决策"。
- TurnPlanAdapter：适配器模式，RoutingResult → 旧 TurnPlan，兼容现有 FlowEngine，
  并完整覆盖状态机：start_flow / resume_flow / cancel_flow / set_slots / 焦点对象映射。
- ToolRouterPlanner：对外暴露与旧 TurnPlanner 一致的 plan(state, user_message) 接口。
"""
from typing import Any

from agent.engine.turn_planner import TurnPlan
from agent.handler.task.flow.models import FlowsList

from .models import (
    Decision,
    ProblemType,
    RoutingResult,
    ToolCall,
    ToolCandidate,
    ToolKind,
)
from .rule_router import RuleRouter
from .tool_registry import ToolRegistry

# GUIDE 主题 → 知识工具（"怎么申请退款" 等，回答步骤而非启动流程）
GUIDE_TOPIC_ANCHORS = [
    ("kb_refund_policy", ["退款", "退钱", "退"]),
    ("kb_enrollment", ["报名", "缴费", "支付", "开通", "买"]),
    ("kb_learning_style", ["上课", "学习", "直播", "录播", "回放"]),
    ("kb_course", ["课程", "班"]),
]

# 焦点对象 → (flow, slot, 取值来源属性)
FOCUSED_MAPPING = {
    "product": ("course_consultation", "course_name", "title"),
    "order": ("order_status_query", "order_number", "id"),
    "cohort": ("learning_progress_query", "cohort_name", "title"),
}


class RoutingOrchestrator:
    """确定性规则 + 四态判决（策略入口在 RouterService 模板方法中）。"""

    def __init__(
        self,
        registry: ToolRegistry,
        rules: RuleRouter,
        flows_list: FlowsList,
        low_threshold: float = 0.40,
        ambiguity_delta: float = 0.20,
    ):
        self._registry = registry
        self._rules = rules
        self._flows = flows_list
        self._low_threshold = low_threshold
        self._ambiguity_delta = ambiguity_delta

    # ---------- 代码级确定性规则 ----------

    async def shortcut_route(self, state, text: str) -> RoutingResult | None:
        """命中的规则直接返回 RoutingResult；否则返回 None 走完整路由。"""
        text = (text or "").strip()
        if not text:
            return RoutingResult(
                problem_type=ProblemType.CHAT,
                decision=Decision.LOW,
                channel="rule",
                skip_llm=True,
            )
        # 1) 取消当前任务
        if state.active_task is not None and self._rules.is_cancel(text):
            return RoutingResult(
                problem_type=ProblemType.ACTION,
                decision=Decision.CLEAR,
                cancel_flow=True,
                channel="rule",
                skip_llm=True,
            )
        # 2) 纯闲聊
        problem = self._rules.detect_problem_type(text)
        if problem == ProblemType.CHAT:
            return RoutingResult(
                problem_type=ProblemType.CHAT,
                decision=Decision.CLEAR,
                selected_tools=[
                    ToolCandidate(name="chitchat", kind=ToolKind.CHITCHAT)
                ],
                channel="rule",
                skip_llm=True,
            )
        # 3) 精确命中知识主题名（课程咨询/报名流程/退款政策/学习方式）→ 知识轨道
        for tool in self._registry.knowledge_tools():
            if tool.executor.get("intent") == text:
                return RoutingResult(
                    problem_type=ProblemType.QUERY,
                    decision=Decision.CLEAR,
                    selected_tools=[
                        ToolCandidate(name=tool.name, kind=ToolKind.KNOWLEDGE)
                    ],
                    channel="rule",
                    skip_llm=True,
                )
        # 4) 指南类：怎么操作/如何申请 → 知识库，不启动流程
        if problem == ProblemType.GUIDE:
            return self._resolve_guide(text)
        # 5) 活跃任务处于 collect 步骤且用户在补充槽位值 → set_slots（无 LLM）
        slot = self._collect_slot(state.active_task) if state.active_task else None
        if slot and not self._rules.is_new_intent(text):
            return RoutingResult(
                problem_type=ProblemType.ACTION,
                decision=Decision.CLEAR,
                selected_tools=[
                    ToolCandidate(
                        name=state.active_task.flow_id,
                        kind=ToolKind.FLOW,
                        parameters={slot: text},
                    )
                ],
                channel="rule",
                skip_llm=True,
            )
        return None

    def _resolve_guide(self, text: str) -> RoutingResult:
        # 1) 知识主题锚点：怎么退款/怎么报名/怎么上课 → 知识库
        for name, anchors in GUIDE_TOPIC_ANCHORS:
            if any(anchor in text for anchor in anchors):
                tool = self._registry.get(name)
                if tool is not None:
                    return RoutingResult(
                        problem_type=ProblemType.GUIDE,
                        decision=Decision.CLEAR,
                        selected_tools=[
                            ToolCandidate(name=tool.name, kind=ToolKind.KNOWLEDGE)
                        ],
                        channel="rule",
                        skip_llm=True,
                    )
        # 2) 查询/执行类指南：怎么查订单/怎么查进度 → 直接启动对应流程
        for tool in self._registry.flow_tools():
            if any(kw and kw in text for kw in tool.keywords):
                return RoutingResult(
                    problem_type=ProblemType.QUERY,
                    decision=Decision.CLEAR,
                    selected_tools=[
                        ToolCandidate(name=tool.name, kind=ToolKind.FLOW)
                    ],
                    channel="rule",
                    skip_llm=True,
                )
        # 3) 知识关键词兜底
        for tool in self._registry.knowledge_tools():
            if any(kw and kw in text for kw in tool.keywords):
                return RoutingResult(
                    problem_type=ProblemType.GUIDE,
                    decision=Decision.CLEAR,
                    selected_tools=[
                        ToolCandidate(name=tool.name, kind=ToolKind.KNOWLEDGE)
                    ],
                    channel="rule",
                    skip_llm=True,
                )
        return RoutingResult(
            problem_type=ProblemType.GUIDE,
            decision=Decision.LOW,
            channel="rule",
            skip_llm=True,
        )

    def _collect_slot(self, active_task) -> str | None:
        step = self._flows.get_step(active_task.flow_id, active_task.step_id)
        if step and step.get("type") == "collect":
            return step.get("slot_name")
        return None

    # ---------- 四态判决 ----------

    def decide(
        self,
        *,
        text: str,
        candidates: list[ToolCandidate],
        reasoning,
        tools: dict[str, Any],
        problem_type: ProblemType | None,
        ranker,
        validator,
    ) -> RoutingResult:
        ranked = ranker.fuse(
            text=text,
            candidates=list(candidates),
            reasoning_calls=reasoning.tool_calls,
            tools=tools,
            problem_type=problem_type,
        )
        # 多意图：LLM 同时命中多个工具 → 澄清（政策可后续改为自动串联）
        if len(reasoning.tool_calls) > 1:
            return RoutingResult(
                problem_type=problem_type,
                decision=Decision.AMBIGUOUS,
                selected_tools=ranked[:2],
                alternatives=ranked[2:4],
                channel="llm",
            )
        if not ranked or ranked[0].final_score < self._low_threshold:
            return RoutingResult(
                problem_type=problem_type,
                decision=Decision.LOW,
                selected_tools=ranked[:1],
                alternatives=ranked[1:3],
                channel="llm",
            )
        # 模糊：top1 与 top2 分数接近 → 澄清
        if (
            len(ranked) >= 2
            and ranked[0].final_score - ranked[1].final_score
            < self._ambiguity_delta
        ):
            return RoutingResult(
                problem_type=problem_type,
                decision=Decision.AMBIGUOUS,
                selected_tools=ranked[:1],
                alternatives=ranked[1:3],
                channel="llm",
            )
        top = ranked[0]
        call_parameters: dict = {}
        for call in reasoning.tool_calls:
            if call.tool == top.name:
                call_parameters = dict(call.parameters or {})
        top.parameters = call_parameters
        missing: list[str] = []
        tool = tools.get(top.name)
        if tool is not None and tool.kind == ToolKind.FLOW:
            missing = validator.missing_required(
                ToolCall(tool=top.name, parameters=call_parameters), tool
            )
        decision = Decision.INSUFFICIENT if missing else Decision.CLEAR
        return RoutingResult(
            problem_type=problem_type,
            decision=decision,
            selected_tools=[top],
            missing_parameters=missing,
            alternatives=ranked[1:3],
            channel="llm",
        )


class TurnPlanAdapter:
    """适配器：RoutingResult + 对话状态 → 旧 TurnPlan（FlowEngine 无需改动）。"""

    def __init__(self, registry: ToolRegistry, flows_list: FlowsList):
        self._registry = registry
        self._flows = flows_list

    def to_turn_plan(self, result: RoutingResult, state) -> TurnPlan:
        if result.cancel_flow:
            return TurnPlan(task={"commands": [{"command": "cancel_flow"}]})
        if result.decision == Decision.AMBIGUOUS:
            return TurnPlan(clarify="multiple_intents")
        if result.decision == Decision.LOW or not result.selected_tools:
            # 置信度低 → 闲聊兜底（chitchat handler 会自然引导回业务）
            return TurnPlan(chitchat={})
        top = result.selected_tools[0]
        tool = self._registry.get(top.name)
        if tool is None:
            return TurnPlan(chitchat={})
        parameters = self._apply_focused_object(tool, dict(top.parameters or {}), state)

        if tool.kind == ToolKind.CHITCHAT:
            return TurnPlan(chitchat={})
        if tool.kind == ToolKind.KNOWLEDGE:
            intent = tool.executor.get("intent")
            return (
                TurnPlan(knowledge={"intents": [intent]})
                if intent
                else TurnPlan(chitchat={})
            )

        flow_id = tool.executor.get("flow") or tool.name
        commands: list[dict] = []
        if state.active_task is not None and state.active_task.flow_id == flow_id:
            commands.append({"command": "set_slots", "slots": parameters})
        elif state.active_task is None and any(
            task.flow_id == flow_id for task in state.paused_tasks
        ):
            commands.append({"command": "resume_flow", "flow": flow_id})
            if parameters:
                commands.append({"command": "set_slots", "slots": parameters})
        else:
            commands.append({"command": "start_flow", "flow": flow_id})
            if parameters:
                commands.append({"command": "set_slots", "slots": parameters})
        return TurnPlan(task={"commands": commands})

    def _apply_focused_object(self, tool, parameters: dict, state) -> dict:
        focused = state.focused_object
        if focused is None:
            return parameters
        mapping = FOCUSED_MAPPING.get(focused.type)
        if mapping is None:
            return parameters
        flow_id, slot, attribute = mapping
        if tool.executor.get("flow") != flow_id:
            return parameters
        if slot not in parameters or parameters[slot] in (None, ""):
            parameters[slot] = getattr(focused, attribute) or focused.id
        return parameters


class ToolRouterPlanner:
    """新的 TurnPlanner：实现与旧版相同的 plan(state, user_message) 接口。

    plan 之后可通过 last_result 查看路由细节（供 trace 观测）。
    """

    def __init__(self, router_service, adapter: TurnPlanAdapter):
        self._service = router_service
        self._adapter = adapter
        self.last_result: RoutingResult | None = None

    async def plan(self, state, user_message) -> TurnPlan:
        result = await self._service.route(state, user_message)
        self.last_result = result
        return self._adapter.to_turn_plan(result, state)

    async def warmup(self) -> None:
        await self._service.warmup()
