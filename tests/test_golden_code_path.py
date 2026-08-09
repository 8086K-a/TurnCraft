"""golden set 代码路径测试：用确定性 FakeLlm 验证路由 + 适配的完整链路。"""
import asyncio
from pathlib import Path

from agent.domain.dialogue_state import DialogueState
from agent.domain.message import MessageType, UserMessage
from agent.handler.task.flow import FlowManager
from agent.handler.task.flow.models import FlowsList
from agent.router import (
    CandidateSelector,
    EmbeddingRecallStrategy,
    HybridRecallStrategy,
    KeywordRecallStrategy,
    ParameterValidator,
    RouteCache,
    RouterService,
    RoutingOrchestrator,
    RuleRouter,
    ToolRanker,
    ToolReasoner,
    ToolRegistry,
    ToolRouterPlanner,
    TurnPlanAdapter,
)
from tests.eval.golden_set import GOLDEN_CASES, judge, llm_responses_by_text

ROOT = Path(__file__).parents[1]


class DisabledEmbedding:
    enabled = False

    def set_tools(self, tools):
        pass

    async def retrieve(self, text, top_k=None):
        return []


class FakeLlm:
    def __init__(self, responses):
        self.responses = responses

    async def ainvoke(self, prompt):
        import re
        match = re.findall(r'"([^"]*)"', prompt)
        user_text = match[-1] if match else ""
        return type("R", (), {"content": self.responses.get(user_text, '{"tool_calls": []}')})()


def build_planner():
    manager = FlowManager()
    manager.load_from_dir(str(ROOT / "flow_config"))
    flows = FlowsList(manager)
    registry = ToolRegistry(manager)
    selector = CandidateSelector(
        HybridRecallStrategy(
            [
                KeywordRecallStrategy(registry.as_dict()),
                EmbeddingRecallStrategy(DisabledEmbedding()),
            ]
        ),
        top_k=8,
    )
    reasoner = ToolReasoner(FakeLlm(llm_responses_by_text()), tools=registry.as_dict())
    service = RouterService(
        registry=registry,
        selector=selector,
        reasoner=reasoner,
        ranker=ToolRanker(),
        validator=ParameterValidator(),
        orchestrator=RoutingOrchestrator(registry, RuleRouter(), flows),
        rules=RuleRouter(),
        cache=RouteCache(maxsize=128),
    )
    return ToolRouterPlanner(service, TurnPlanAdapter(registry, flows))


def test_golden_cases_code_path():
    planner = build_planner()

    async def scenario():
        failures = []
        for case in GOLDEN_CASES:
            state = DialogueState(sender_id="golden")
            plan = await planner.plan(
                state,
                UserMessage(
                    sender_id="golden",
                    message_id=case["text"],
                    type=MessageType.TEXT,
                    text=case["text"],
                ),
            )
            ok, detail = judge(plan, case)
            if not ok:
                failures.append((case["text"], detail, plan.model_dump(mode="json")))
        assert not failures, f"golden failures: {failures}"

    asyncio.run(scenario())
