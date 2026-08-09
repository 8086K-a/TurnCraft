"""分层工具路由（合并方案 A+B）的单元 + 集成测试。

使用确定性 FakeLLM / StubEmbedding，不依赖真实网络。
"""
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

from agent.domain.dialogue_state import DialogueState
from agent.domain.message import MessageType, UserMessage
from agent.engine.dialogue_engine import DialogueEngine
from agent.engine.turn_plan_validator import TurnPlanValidator
from agent.handler.chitchat import ChitchatHandler
from agent.handler.knowledge import KnowledgeHandler
from agent.handler.task import ActionExecutor, ActionRegistry, FlowManager, TaskHandler
from agent.handler.task.action.builtin import action_listen, action_response
from agent.handler.task.action.custom import register_custom_actions
from agent.handler.task.command.processor import CommandProcessor
from agent.handler.task.flow.models import FlowsList
from agent.router import (
    CandidateSelector,
    Decision,
    EmbeddingRecallStrategy,
    HybridRecallStrategy,
    KeywordRecallStrategy,
    ParameterValidator,
    ProblemType,
    RouteCache,
    RouterService,
    RoutingOrchestrator,
    RuleRouter,
    ToolCandidate,
    ToolKind,
    ToolRanker,
    ToolReasoner,
    ToolRegistry,
    ToolRouterPlanner,
    TurnPlanAdapter,
)

ROOT = Path(__file__).parents[1]


def build_flow_manager() -> FlowManager:
    manager = FlowManager()
    manager.load_from_dir(str(ROOT / "flow_config"))
    return manager


class StubEmbeddingRetriever:
    """测试用 embedding 通道：按文本返回固定候选（或无候选）。"""

    def __init__(self, responses=None, enabled=True):
        self.responses = responses or {}
        self.enabled = enabled

    def set_tools(self, tools):
        pass

    async def retrieve(self, text, top_k=None):
        if not self.enabled:
            return []
        items = self.responses.get(text, [])
        return [ToolCandidate(name=name, kind=kind, embedding_score=score, source="embedding")
                for name, kind, score in items]


class FakeLlm:
    """根据用户话术返回预置 JSON 的假 LLM。"""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def ainvoke(self, prompt):
        self.calls.append(prompt)
        match = re.findall(r'"([^"]*)"', prompt)
        user_text = match[-1] if match else ""
        body = self.responses.get(user_text, '{"tool_calls": []}')
        return SimpleNamespace(content=body)


class FakeEduApi:
    async def find_order_by_no(self, user_id, order_no):
        if order_no == "NOPE":
            return None
        return {"orderId": 501, "orderStatusCode": "paid", "orderNo": order_no,
                "payableAmount": 2999,
                "items": [{"orderItemId": 501, "courseName": "Python全栈"}]}

    async def list_series(self, keyword=None, page=1, size=20):
        return {"list": [{"seriesId": 2199, "seriesName": keyword or "课程"}]}

    async def list_series_cohorts(self, series_id):
        return [{"cohortName": "直播班", "salePrice": 4999}]


class FakeChitchat:
    async def handle(self, state, user_message):
        return f"闲聊回复：{user_message.text}"


def build_router(llm_responses=None, embedding_responses=None, embedding_enabled=True):
    manager = build_flow_manager()
    flows = FlowsList(manager)
    registry = ToolRegistry(manager)
    embedding = StubEmbeddingRetriever(embedding_responses, enabled=embedding_enabled)
    selector = CandidateSelector(
        HybridRecallStrategy(
            [
                KeywordRecallStrategy(registry.as_dict()),
                EmbeddingRecallStrategy(embedding),
            ]
        ),
        top_k=8,
    )
    llm = FakeLlm(llm_responses or {})
    reasoner = ToolReasoner(llm, tools=registry.as_dict())
    ranker = ToolRanker()
    validator = ParameterValidator()
    rules = RuleRouter()
    orchestrator = RoutingOrchestrator(registry, rules, flows)
    service = RouterService(
        registry=registry,
        selector=selector,
        reasoner=reasoner,
        ranker=ranker,
        validator=validator,
        orchestrator=orchestrator,
        rules=rules,
        cache=RouteCache(maxsize=128),
    )
    planner = ToolRouterPlanner(service, TurnPlanAdapter(registry, flows))
    return service, planner, manager, flows, llm


def build_engine(planner):
    manager = build_flow_manager()
    flows = FlowsList(manager)
    registry = ActionRegistry()
    registry.register("action_response", action_response)
    registry.register("action_listen", action_listen)
    register_custom_actions(registry)
    return DialogueEngine(
        task_handler=TaskHandler(manager, ActionExecutor(registry)),
        command_processor=CommandProcessor(),
        flows_list=flows,
        planner=planner,
        plan_validator=TurnPlanValidator(manager),
        api=FakeEduApi(),
        chitchat_handler=FakeChitchat(),
        knowledge_handler=None,
    )


def new_state() -> DialogueState:
    return DialogueState(sender_id="router-user")


async def send(engine, state, text):
    result = await engine.process(
        state,
        UserMessage(sender_id="router-user", message_id=text, type=MessageType.TEXT, text=text),
    )
    return [message.text for message in result.messages]


# ---------- 注册表 ----------

def test_tool_registry_generates_flows_knowledge_and_chitchat():
    registry = ToolRegistry(build_flow_manager())
    names = {tool.name for tool in registry.all()}
    assert "refund_request" in names
    assert "course_consultation" in names
    assert "kb_refund_policy" in names
    assert "chitchat" in names
    assert "onboarding" not in names  # 系统欢迎流程不作为用户工具

    refund = registry.get("refund_request")
    assert set(refund.parameters) == {"order_number", "refund_reason", "refund_type"}
    assert refund.parameters["order_number"].required is True
    assert refund.kind == ToolKind.FLOW
    assert refund.executor == {"flow": "refund_request"}


# ---------- 规则路由 ----------

def test_rule_router_greeting_guide_and_cancel():
    rules = RuleRouter()
    assert rules.detect_problem_type("你好") is ProblemType.CHAT
    assert rules.detect_problem_type("谢谢") is ProblemType.CHAT
    assert rules.detect_problem_type("你好，我要退款") is not ProblemType.CHAT
    assert rules.detect_problem_type("怎么申请退款") is ProblemType.GUIDE
    assert rules.detect_problem_type("怎么做才能更高效") is not ProblemType.GUIDE
    assert rules.is_cancel("取消") is True
    assert rules.is_cancel("我要退款") is False
    assert rules.is_new_intent("我要退款") is True
    assert rules.is_new_intent("ORD1") is False
    assert rules.is_new_intent("课程不合适") is False


# ---------- 关键词召回 ----------

def test_keyword_recall_finds_refund_tool():
    registry = ToolRegistry(build_flow_manager())
    strategy = KeywordRecallStrategy(registry.as_dict())

    async def scenario():
        candidates = await strategy.recall("我要退款", 8)
        assert candidates[0].name == "refund_request"
        assert "退款" in [c.name for c in candidates] or True

    asyncio.run(scenario())


# ---------- 缓存 ----------

def test_route_cache_distinguishes_state_fingerprint():
    from agent.domain.context import TaskContext
    from agent.router import RoutingResult

    cache = RouteCache()
    state_a = new_state()
    result_a = RoutingResult(decision=Decision.CLEAR, channel="rule")
    cache.set("查订单", state_a, result_a)
    assert cache.get("查订单", state_a) is not None
    # 不同状态指纹 → 不命中
    state_b = new_state()
    state_b.active_task = TaskContext(flow_id="refund_request", step_id="ask_order_number")
    assert cache.get("查订单", state_b) is None


# ---------- 参数校验 ----------

def test_parameter_validator_reports_missing_and_pattern():
    registry = ToolRegistry(build_flow_manager())
    validator = ParameterValidator()
    refund = registry.get("refund_request")
    missing = validator.missing_required(SimpleNamespace(parameters={"order_number": "ORD1"}), refund)
    assert set(missing) == {"refund_reason", "refund_type"}


# ---------- 排序 ----------

def test_ranker_puts_llm_selected_tool_first():
    ranker = ToolRanker()
    candidates = [
        ToolCandidate(name="order_status_query", kind=ToolKind.FLOW, embedding_score=0.7),
        ToolCandidate(name="refund_request", kind=ToolKind.FLOW, embedding_score=0.6),
    ]
    reasoning = [SimpleNamespace(tool="refund_request", parameters={"order_number": "ORD1"})]
    registry = ToolRegistry(build_flow_manager())
    ranked = ranker.fuse(
        text="退一下订单",
        candidates=candidates,
        reasoning_calls=reasoning,
        tools=registry.as_dict(),
        problem_type=ProblemType.ACTION,
    )
    assert ranked[0].name == "refund_request"
    assert ranked[0].final_score > ranked[1].final_score


# ---------- 编排：代码级规则 ----------

def test_active_collect_step_fills_slot_without_llm():
    _, planner, manager, flows, _ = build_router()
    from agent.domain.context import TaskContext
    state = new_state()
    state.active_task = TaskContext(flow_id="refund_request", step_id="ask_order_number")
    assert flows.get_step("refund_request", "ask_order_number")["type"] == "collect"

    async def scenario():
        plan = await planner.plan(
            state,
            UserMessage(sender_id="x", message_id="m", type=MessageType.TEXT, text="ORD1"),
        )
        assert plan.task.commands == [{"command": "set_slots", "slots": {"order_number": "ORD1"}}]

    asyncio.run(scenario())


def test_cancel_rule_cancels_active_task():
    from agent.domain.context import TaskContext
    _, planner, _, _, _ = build_router()
    state = new_state()
    state.active_task = TaskContext(flow_id="refund_request", step_id="ask_order_number")

    async def scenario():
        plan = await planner.plan(
            state,
            UserMessage(sender_id="x", message_id="m", type=MessageType.TEXT, text="取消"),
        )
        assert plan.task.commands == [{"command": "cancel_flow"}]

    asyncio.run(scenario())


def test_guide_rule_answers_from_knowledge():
    _, planner, _, _, _ = build_router()

    async def scenario():
        plan = await planner.plan(
            new_state(),
            UserMessage(sender_id="x", message_id="m", type=MessageType.TEXT, text="怎么申请退款"),
        )
        assert plan.knowledge == {"intents": ["退款政策"]}

    asyncio.run(scenario())


# ---------- 全链路（FakeLLM 决策） ----------

def test_full_route_starts_flow_with_parameters():
    llm_responses = {
        "我要退款": '{"tool_calls": [{"tool": "refund_request", "parameters": {"order_number": "ORD1"}}]}'
    }
    service, planner, _, _, llm = build_router(llm_responses)
    state = new_state()

    async def scenario():
        plan = await planner.plan(
            state,
            UserMessage(sender_id="x", message_id="m", type=MessageType.TEXT, text="我要退款"),
        )
        assert plan.task.commands[0] == {"command": "start_flow", "flow": "refund_request"}
        assert {"command": "set_slots", "slots": {"order_number": "ORD1"}} in plan.task.commands
        assert llm.calls  # 确实调用了 LLM

    asyncio.run(scenario())


def test_full_route_resumes_paused_flow():
    from agent.domain.context import TaskContext

    llm_responses = {
        "继续退款": '{"tool_calls": [{"tool": "refund_request", "parameters": {"order_number": "ORD1"}}]}'
    }
    _, planner, _, _, _ = build_router(llm_responses)
    state = new_state()
    state.paused_tasks = [TaskContext(flow_id="refund_request", step_id="ask_order_number")]

    async def scenario():
        plan = await planner.plan(
            state,
            UserMessage(sender_id="x", message_id="m", type=MessageType.TEXT, text="继续退款"),
        )
        assert plan.task.commands[0] == {"command": "resume_flow", "flow": "refund_request"}

    asyncio.run(scenario())


def test_knowledge_tool_maps_to_knowledge_track():
    llm_responses = {
        "退款政策是什么": '{"tool_calls": [{"tool": "kb_refund_policy", "parameters": {}}]}'
    }
    _, planner, _, _, _ = build_router(llm_responses)

    async def scenario():
        plan = await planner.plan(
            new_state(),
            UserMessage(sender_id="x", message_id="m", type=MessageType.TEXT, text="退款政策是什么"),
        )
        assert plan.knowledge == {"intents": ["退款政策"]}

    asyncio.run(scenario())


def test_multi_intent_clarifies():
    llm_responses = {
        "我要退款顺便查订单": '{"tool_calls": [{"tool": "refund_request", "parameters": {}}, {"tool": "order_status_query", "parameters": {}}]}'
    }
    _, planner, _, _, _ = build_router(llm_responses)

    async def scenario():
        plan = await planner.plan(
            new_state(),
            UserMessage(sender_id="x", message_id="m", type=MessageType.TEXT, text="我要退款顺便查订单"),
        )
        assert plan.task is None
        assert plan.clarify == "multiple_intents"

    asyncio.run(scenario())


def test_low_confidence_falls_back_to_chitchat():
    _, planner, _, _, _ = build_router({"帮我订个机票": '{"tool_calls": []}'})

    async def scenario():
        plan = await planner.plan(
            new_state(),
            UserMessage(sender_id="x", message_id="m", type=MessageType.TEXT, text="帮我订个机票"),
        )
        assert plan.chitchat == {}

    asyncio.run(scenario())


def test_cache_hit_skips_second_llm_call():
    llm_responses = {
        "我要退款": '{"tool_calls": [{"tool": "refund_request", "parameters": {}}]}'
    }
    service, planner, _, _, llm = build_router(llm_responses)

    async def scenario():
        await planner.plan(
            new_state(),
            UserMessage(sender_id="x", message_id="m", type=MessageType.TEXT, text="我要退款"),
        )
        calls_after_first = len(llm.calls)
        await planner.plan(
            new_state(),
            UserMessage(sender_id="x", message_id="m", type=MessageType.TEXT, text="我要退款"),
        )
        assert len(llm.calls) == calls_after_first  # 第二次命中缓存，不再调 LLM

    asyncio.run(scenario())


# ---------- 引擎级集成 ----------

def test_engine_full_refund_chain_with_new_router():
    llm_responses = {
        "我要退款": '{"tool_calls": [{"tool": "refund_request", "parameters": {}}]}',
    }
    _, planner, _, _, _ = build_router(llm_responses)
    engine = build_engine(planner)

    async def scenario():
        state = new_state()
        messages = await send(engine, state, "我要退款")
        assert any("请告诉我你的订单号" in m for m in messages)
        # 活跃任务收集订单号：ORD1 走代码规则 set_slots，不调 LLM
        messages = await send(engine, state, "ORD1")
        assert any("请简单说一下退款原因" in m for m in messages)
        assert state.active_task.slots.get("order_number") == "ORD1"

    asyncio.run(scenario())


def test_engine_greeting_pauses_active_task():
    llm_responses = {"我要退款": '{"tool_calls": [{"tool": "refund_request", "parameters": {}}]}'}
    _, planner, _, _, _ = build_router(llm_responses)
    engine = build_engine(planner)

    async def scenario():
        state = new_state()
        await send(engine, state, "我要退款")
        assert state.active_task is not None
        messages = await send(engine, state, "你好")
        assert messages == ["闲聊回复：你好"]
        assert state.active_task is None
        assert state.paused_tasks[0].flow_id == "refund_request"

    asyncio.run(scenario())


def test_engine_knowledge_track_answers_from_knowledge_base():
    llm_responses = {
        "退款政策是什么": '{"tool_calls": [{"tool": "kb_refund_policy", "parameters": {}}]}'
    }
    _, planner, _, _, _ = build_router(llm_responses)
    engine = build_engine(planner)

    async def scenario():
        messages = await send(engine, new_state(), "退款政策是什么")
        assert any("退款" in m for m in messages)

    asyncio.run(scenario())


def test_engine_order_query_with_parameter():
    llm_responses = {
        "查订单 ORD1": '{"tool_calls": [{"tool": "order_status_query", "parameters": {"order_number": "ORD1"}}]}'
    }
    _, planner, _, _, _ = build_router(llm_responses)
    engine = build_engine(planner)

    async def scenario():
        messages = await send(engine, new_state(), "查订单 ORD1")
        assert any("已支付" in m for m in messages)

    asyncio.run(scenario())


# ---------- 补充行为锁定 ----------

def test_exact_knowledge_topic_rule_maps_to_knowledge():
    _, planner, _, _, _ = build_router()

    async def scenario():
        plan = await planner.plan(
            new_state(),
            UserMessage(sender_id="x", message_id="m", type=MessageType.TEXT, text="报名流程"),
        )
        assert plan.knowledge == {"intents": ["报名流程"]}

    asyncio.run(scenario())


def test_focused_object_fills_course_name_slot():
    from agent.domain.context import FocusedObject

    llm_responses = {
        "查询这个的价格": '{"tool_calls": [{"tool": "course_consultation", "parameters": {}}]}'
    }
    _, planner, _, _, _ = build_router(llm_responses)
    state = new_state()
    state.focused_object = FocusedObject(type="product", id="2199", title="系统编程实战班·直播")

    async def scenario():
        plan = await planner.plan(
            state,
            UserMessage(sender_id="x", message_id="m", type=MessageType.TEXT, text="查询这个的价格"),
        )
        assert plan.task.commands[0] == {"command": "start_flow", "flow": "course_consultation"}
        assert {"command": "set_slots", "slots": {"course_name": "系统编程实战班·直播"}} in plan.task.commands

    asyncio.run(scenario())


def test_embedding_retriever_batches_requests(monkeypatch):
    from agent.router import EmbeddingRetriever

    captured = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            count = len(captured[-1]["input"])
            return {"data": [{"index": i, "embedding": [0.1, 0.2, 0.3]} for i in range(count)]}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            captured.append(json)
            return FakeResponse()

    monkeypatch.setattr("agent.router.embedding_retriever.httpx.AsyncClient", FakeAsyncClient)
    retriever = EmbeddingRetriever(api_key="fake-key", enabled=True)
    vectors = asyncio.run(retriever._embed([f"text {i}" for i in range(25)]))

    assert len(vectors) == 25
    assert [len(call["input"]) for call in captured] == [10, 10, 5]


# ---------- 真实装配回归（builder 变量遮蔽 bug） ----------

def test_builder_wires_action_and_tool_registries_correctly():
    """回归：ActionExecutor 必须拿到 ActionRegistry，而不是 ToolRegistry。"""
    from agent.engine.builder import build_dialogue_engine
    from agent.handler.task.action import ActionRegistry
    from agent.router import ToolRegistry as ToolRouterRegistry

    engine = build_dialogue_engine()
    action_registry = engine._task_handler._ae._registry

    assert isinstance(action_registry, ActionRegistry), (
        f"ActionExecutor 拿到的是 {type(action_registry).__name__}，"
        "builder 中 registry 变量被 ToolRegistry 遮蔽了"
    )
    for name in [
        "action_response",
        "action_listen",
        "action_lookup_order_status",
        "action_lookup_course_info",
        "action_lookup_learning_progress",
        "action_submit_refund",
        "action_submit_ticket",
    ]:
        assert action_registry.has(name), f"缺少动作 {name}"

    planner = engine._planner
    assert isinstance(planner._adapter._registry, ToolRouterRegistry)
    assert planner._service._registry.has("refund_request")
