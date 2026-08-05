import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent.api.app import app
from agent.api.dependencies import get_dialogue_service
from agent.domain.message import MessageType, UserMessage
from agent.engine.dialogue_engine import DialogueEngine
from agent.engine.turn_planner import TurnPlan, TurnPlanner
from agent.domain.dialogue_state import DialogueState
from agent.handler.task import ActionExecutor, ActionRegistry, FlowManager, TaskHandler
from agent.handler.task.action.builtin import action_listen, action_response
from agent.handler.task.action.custom import register_custom_actions
from agent.handler.task.command.processor import CommandProcessor
from agent.handler.task.flow.models import FlowsList
from agent.handler.task.flow.loader import FlowLoader
from agent.handler.chitchat import ChitchatHandler
from agent.repository.dialogue_state_repository import DialogueStateRepository
from agent.service.dialogue_service import DialogueService


class FakePlanner:
    def __init__(self):
        self.calls = []

    async def plan(self, state, user_message):
        history = TurnPlanner._history(state)
        self.calls.append((user_message.text, history))
        if user_message.object is not None:
            return TurnPlan(
                task={"commands": [{"command": "start_flow", "flow": "course_consultation"}]}
            )
        text = user_message.text
        if text == "你好":
            return TurnPlan(chitchat={})
        if text == "你好，我要退款":
            return TurnPlan(
                task={"commands": [{"command": "start_flow", "flow": "refund_request"}]},
                chitchat={},
            )
        if text == "先处理退款" and "我同时听到了几个需求" in history:
            return TurnPlan(
                task={"commands": [{"command": "start_flow", "flow": "refund_request"}]}
            )
        if text == "课程咨询":
            return TurnPlan(knowledge={"intents": ["课程咨询"]})
        if text == "查询这个的价格":
            return TurnPlan(
                task={
                    "commands": [
                        {"command": "start_flow", "flow": "course_consultation"},
                        {
                            "command": "set_slots",
                            "slots": {
                                "course_name": state.focused_object.title,
                            },
                        },
                    ]
                }
            )
        plans = {
            "我想咨询课程": [{"command": "start_flow", "flow": "course_consultation"}],
            "Python全栈": [{"command": "set_slots", "slots": {"course_name": "Python全栈"}}],
            "我想了解编程课程": [
                {"command": "start_flow", "flow": "course_consultation"},
                {"command": "set_slots", "slots": {"course_name": "编程"}},
            ],
            "Python进阶": [{"command": "set_slots", "slots": {"course_name": "Python进阶"}}],
            "我要退款": [{"command": "start_flow", "flow": "refund_request"}],
            "ORD1": ([
                {"command": "resume_flow", "flow": "refund_request"},
                {"command": "set_slots", "slots": {"order_number": "ORD1"}},
            ] if state.active_task is None and state.paused_tasks else [
                {"command": "set_slots", "slots": {"order_number": "ORD1"}}
            ]),
            "课程不合适": [{"command": "set_slots", "slots": {"refund_reason": "课程不合适"}}],
            "课程不满意": [{"command": "set_slots", "slots": {"refund_type": "课程不满意"}}],
            "查订单 ORD1": [
                {"command": "start_flow", "flow": "order_status_query"},
                {"command": "set_slots", "slots": {"order_number": "ORD1"}},
            ],
            "查订单": [{"command": "start_flow", "flow": "order_status_query"}],
            "查订单 NOPE": [
                {"command": "start_flow", "flow": "order_status_query"},
                {"command": "set_slots", "slots": {"order_number": "NOPE"}},
            ],
            "我要投诉": [{"command": "start_flow", "flow": "ticket_submission"}],
            "投诉": [{"command": "set_slots", "slots": {"ticket_type": "投诉"}}],
            "视频无法播放": [{"command": "set_slots", "slots": {"ticket_description": "视频无法播放"}}],
            "取消": [{"command": "cancel_flow"}],
            "继续退款": [{"command": "resume_flow", "flow": "refund_request"}],
            "无效恢复": [{"command": "resume_flow", "flow": "refund_request"}],
        }
        return TurnPlan.model_validate({"task": {"commands": plans[text]}})


class FakeChitchatHandler:
    async def handle(self, state, user_message):
        return f"闲聊回复：{user_message.text}"


class FakeEduApi:
    def __init__(self):
        self.writes = []

    async def find_order_by_no(self, user_id, order_no):
        if order_no != "ORD1":
            return None
        return {
            "orderId": 101,
            "orderNo": "ORD1",
            "orderStatusCode": "paid",
            "payableAmount": 2999,
            "paymentSummary": {"paidAt": "2026-07-01"},
            "items": [
                {
                    "orderItemId": 501,
                    "courseName": "Python全栈",
                    "payableAmount": 2999,
                }
            ],
        }

    async def create_refund_request(self, **kwargs):
        self.writes.append(("refund", kwargs))
        return {"refundRequestNo": "REF1"}

    async def get_my_student_profile(self, user_id):
        return {"studentId": 301}

    async def list_series(self, keyword=None, page=1, size=20):
        if keyword == "编程":
            return {
                "list": [
                    {"seriesId": 2200, "seriesName": "Python入门"},
                    {"seriesId": 2201, "seriesName": "Python进阶"},
                ]
            }
        if keyword == "Python进阶":
            return {"list": [{"seriesId": 2201, "seriesName": "Python进阶"}]}
        return {"list": [{"seriesId": 2199, "seriesName": keyword or "课程"}]}

    async def list_series_cohorts(self, series_id):
        return [{"cohortName": "直播班", "salePrice": 4999, "startDate": "2026-08-01"}]

    async def create_service_ticket(self, **kwargs):
        self.writes.append(("ticket", kwargs))
        return {"ticketNo": "TICKET1"}


def build_service():
    manager = FlowManager()
    manager.load_from_dir(str(Path(__file__).parents[1] / "flow_config"))
    registry = ActionRegistry()
    registry.register("action_response", action_response)
    registry.register("action_listen", action_listen)
    register_custom_actions(registry)
    api = FakeEduApi()
    engine = DialogueEngine(
        task_handler=TaskHandler(manager, ActionExecutor(registry)),
        command_processor=CommandProcessor(),
        flows_list=FlowsList(manager),
        planner=FakePlanner(),
        api=api,
        chitchat_handler=FakeChitchatHandler(),
    )
    repository = DialogueStateRepository()
    return DialogueService(repository, engine), repository, api


async def send(service, sender_id, text):
    result = await service.process_message(
        UserMessage(
            sender_id=sender_id,
            message_id=text,
            type=MessageType.TEXT,
            text=text,
        )
    )
    return [message.text for message in result.messages]


async def send_object(service, sender_id, object_type, object_id, title=None):
    result = await service.process_message(
        UserMessage(
            sender_id=sender_id,
            message_id=f"object-{object_id}",
            type=MessageType.OBJECT,
            object={"type": object_type, "id": object_id, "title": title},
        )
    )
    return [message.text for message in result.messages]


def test_refund_multiturn_state_and_order_item_id():
    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, api = build_service()

        assert "请告诉我你的订单号。" in await send(service, "u1", "我要退款")
        assert "请简单说一下退款原因。" in await send(service, "u1", "ORD1")
        assert any("退款类型" in text for text in await send(service, "u1", "课程不合适"))
        result = await send(service, "u1", "课程不满意")

        assert any("REF1" in text for text in result)
        assert api.writes[0][1]["order_item_id"] == 501
        assert api.writes[0][1]["refund_type"] == "course_unsatisfied"
        state = await repository.load("u1")
        assert state.active_task is None
        assert state.paused_tasks == []
        assert len(state.sessions[0].turns) == 4

    asyncio.run(scenario())


def test_order_object_fills_current_order_number_slot():
    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, _ = build_service()

        await send(service, "object-user", "我要退款")
        result = await send_object(service, "object-user", "order", "ORD1")

        assert "请简单说一下退款原因。" in result
        state = await repository.load("object-user")
        assert state.active_task.slots["order_number"] == "ORD1"

    asyncio.run(scenario())


def test_product_object_is_used_by_course_lookup_action():
    async def scenario():
        await DialogueStateRepository.clear()
        service, _, _ = build_service()

        result = await send_object(
            service, "course-object-user", "product", "2199", "系统编程实战班·直播"
        )

        assert result == ["你想了解这个商品的课程信息、价格，还是其他内容？"]
        result = await send(service, "course-object-user", "查询这个的价格")
        assert any("系统编程实战班·直播" in text for text in result)
        assert not any("请告诉我你想了解的课程名称" in text for text in result)

    asyncio.run(scenario())


def test_course_consultation_collects_name_before_lookup():
    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, _ = build_service()

        started = await send(service, "course-user", "我想咨询课程")
        assert "请告诉我你想了解的课程名称。" in started
        waiting = await repository.load("course-user")
        assert waiting.active_task.flow_id == "course_consultation"
        assert waiting.active_task.step_id == "ask_course_name"

        result = await send(service, "course-user", "Python全栈")
        assert any("Python全栈" in text for text in result)
        completed = await repository.load("course-user")
        assert completed.active_task is None
        assert completed.active_system_flow is None

    asyncio.run(scenario())


def test_course_consultation_clarifies_multiple_matches():
    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, _ = build_service()

        choices = await send(service, "course-choice-user", "我想了解编程课程")
        assert any("Python入门、Python进阶" in text for text in choices)
        waiting = await repository.load("course-choice-user")
        assert waiting.active_task.flow_id == "course_consultation"
        assert waiting.active_task.step_id == "ask_course_choice"
        assert waiting.active_task.slots["course_name"] is None

        result = await send(service, "course-choice-user", "Python进阶")
        assert any("课程：Python进阶" in text for text in result)
        assert (await repository.load("course-choice-user")).active_task is None

    asyncio.run(scenario())


def test_completed_interrupting_task_returns_idle_and_keeps_previous_task_paused():
    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, _ = build_service()

        await send(service, "u2", "我要退款")
        result = await send(service, "u2", "查订单 ORD1")

        assert any("已支付" in text for text in result)
        assert not any("继续刚才的退款申请" in text for text in result)
        state = await repository.load("u2")
        assert state.active_task is None
        assert state.active_system_flow is None
        assert [task.flow_id for task in state.paused_tasks] == ["refund_request"]

    asyncio.run(scenario())


def test_action_failure_does_not_emit_a_false_success_response():
    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, _ = build_service()

        result = await send(service, "u3", "查订单 NOPE")

        assert result[-1] == "未找到订单 NOPE。"
        assert not any("当前状态" in text for text in result)
        assert (await repository.load("u3")).active_task is None

    asyncio.run(scenario())


def test_ticket_returns_number_and_uses_order_item_id():
    async def scenario():
        await DialogueStateRepository.clear()
        service, _, api = build_service()

        await send(service, "u4", "我要投诉")
        await send(service, "u4", "投诉")
        await send(service, "u4", "ORD1")
        result = await send(service, "u4", "视频无法播放")

        assert any("TICKET1" in text for text in result)
        assert api.writes[0][1]["order_item_id"] == 501

    asyncio.run(scenario())


def test_chat_http_endpoint_runs_the_task_chain():
    asyncio.run(DialogueStateRepository.clear())
    service, _, _ = build_service()
    app.dependency_overrides[get_dialogue_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={"sender_id": "http-user", "text": "查订单 ORD1"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    messages = [item["text"] for item in response.json()["messages"]]
    assert any("已支付" in text for text in messages)
    assert any("Python全栈" in text for text in messages)


def test_chat_history_http_endpoint_returns_real_session_messages():
    async def scenario():
        await DialogueStateRepository.clear()
        service, _, _ = build_service()
        await send(service, "history-http-user", "你好")

    asyncio.run(scenario())
    app.dependency_overrides[get_dialogue_service] = lambda: build_service()[0]
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/chat/history", params={"sender_id": "history-http-user"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    history = response.json()["messages"]
    assert history[0]["role"] == "user"
    assert history[0]["text"] == "你好"
    assert history[1]["role"] == "bot"


def test_cancel_foreground_task_returns_idle_and_keeps_previous_task_paused():
    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, _ = build_service()

        await send(service, "u5", "我要退款")
        await send(service, "u5", "查订单")
        result = await send(service, "u5", "取消")

        assert any("订单状态查询先帮你取消" in text for text in result)
        assert not any("继续刚才的退款申请" in text for text in result)
        state = await repository.load("u5")
        assert state.active_task is None
        assert state.active_system_flow is None
        assert [task.flow_id for task in state.paused_tasks] == ["refund_request"]

    asyncio.run(scenario())


def test_explicit_resume_pauses_foreground_and_finishes_in_idle_state():
    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, _ = build_service()

        await send(service, "u6", "我要退款")
        await send(service, "u6", "查订单")
        resumed = await send(service, "u6", "继续退款")
        assert any("先把订单状态查询放一放" in text for text in resumed)

        await send(service, "u6", "ORD1")
        await send(service, "u6", "课程不合适")
        completed = await send(service, "u6", "课程不满意")

        assert not any("继续刚才的订单状态查询" in text for text in completed)
        state = await repository.load("u6")
        assert state.active_task is None
        assert state.active_system_flow is None
        assert [task.flow_id for task in state.paused_tasks] == ["order_status_query"]

    asyncio.run(scenario())


def test_invalid_resume_is_a_closed_noop_with_a_response():
    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, _ = build_service()

        result = await send(service, "u7", "无效恢复")

        assert result == ["当前没有可继续处理的任务。"]
        state = await repository.load("u7")
        assert state.active_task is None
        assert state.paused_tasks == []

    asyncio.run(scenario())


def test_flow_loader_uses_the_same_runtime_flow_model():
    root = Path(__file__).parents[1] / "flow_config"
    flows = FlowLoader().load_many(
        [root / "system_flows.yml", root / "user_flows.yml"]
    )

    assert flows.get_flow_by_id("refund_request").name == "退款申请"
    assert flows.get_flow_by_id("system_task_resumed") is not None
    assert "order_number" in flows.slots


def test_production_turn_planner_parses_fenced_json():
    class FakeLlm:
        def __init__(self):
            self.prompt = ""

        async def ainvoke(self, prompt):
            self.prompt = prompt
            return SimpleNamespace(
                content='```json\n{"task":{"commands":[{"command":"start_flow","flow":"order_status_query"}]},"knowledge":null,"chitchat":null}\n```'
            )

    async def scenario():
        manager = FlowManager()
        manager.load_from_dir(str(Path(__file__).parents[1] / "flow_config"))
        llm = FakeLlm()
        planner = TurnPlanner(llm, manager)
        message = UserMessage(
            sender_id="planner-user",
            message_id="planner-message",
            type=MessageType.TEXT,
            text="查订单",
        )

        plan = await planner.plan(DialogueState(sender_id="planner-user"), message)

        assert plan.task.commands[0]["flow"] == "order_status_query"
        assert "refund_request" in llm.prompt
        assert "查订单" in llm.prompt

    asyncio.run(scenario())


def test_chitchat_track_returns_a_response_and_records_history():
    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, _ = build_service()

        result = await send(service, "chat-user", "你好")

        assert result == ["闲聊回复：你好"]
        state = await repository.load("chat-user")
        assert state.active_task is None
        assert state.sessions[0].turns[0].assistant_messages[0].text == "闲聊回复：你好"

    asyncio.run(scenario())


def test_chitchat_does_not_advance_or_clear_an_active_task():
    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, _ = build_service()

        await send(service, "chat-task-user", "我要退款")
        before = await repository.load("chat-task-user")
        assert before.active_task.step_id == "ask_order_number"

        assert await send(service, "chat-task-user", "你好") == ["闲聊回复：你好"]
        after = await repository.load("chat-task-user")
        assert after.active_task is None
        assert after.paused_tasks[0].flow_id == "refund_request"
        assert after.paused_tasks[0].step_id == "ask_order_number"
        assert after.paused_tasks[0].slots == {}

        continued = await send(service, "chat-task-user", "ORD1")
        assert "请简单说一下退款原因。" in continued

    asyncio.run(scenario())


def test_multiple_tracks_are_clarified_without_starting_a_task():
    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, _ = build_service()

        result = await send(service, "multi-track-user", "你好，我要退款")

        assert result == ["我同时听到了几个需求，你想先处理哪一个？"]
        assert (await repository.load("multi-track-user")).active_task is None

    asyncio.run(scenario())


def test_clarification_choice_is_replanned_from_natural_language():
    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, _ = build_service()

        await send(service, "clarify-user", "你好，我要退款")
        result = await send(service, "clarify-user", "先处理退款")

        assert "请告诉我你的订单号。" in result
        state = await repository.load("clarify-user")
        assert state.active_task.flow_id == "refund_request"
        planner = service._engine._planner
        assert [text for text, _ in planner.calls] == ["你好，我要退款", "先处理退款"]
        assert "我同时听到了几个需求" in planner.calls[-1][1]
        assert not hasattr(state, "pending_clarification")

    asyncio.run(scenario())


def test_knowledge_intent_is_answered_by_knowledge_handler():
    async def scenario():
        await DialogueStateRepository.clear()
        service, _, _ = build_service()

        result = await send(service, "knowledge-user", "课程咨询")

        assert result == [
            "我们的课程涵盖编程、数据分析、人工智能等多个方向。编程课程分为入门班、项目班和就业强化班三种层次，采用直播或录播形式授课，学费从2499元到6999元不等。"
        ]

    asyncio.run(scenario())


def test_production_chitchat_handler_uses_history_and_normalizes_content():
    class FakeLlm:
        def __init__(self):
            self.prompt = ""

        async def ainvoke(self, prompt):
            self.prompt = prompt
            return SimpleNamespace(content=[{"type": "text", "text": "你好，很高兴见到你。"}])

    async def scenario():
        await DialogueStateRepository.clear()
        service, repository, _ = build_service()
        await send(service, "history-chat-user", "我要退款")
        state = await repository.load("history-chat-user")
        llm = FakeLlm()
        handler = ChitchatHandler(llm)
        message = UserMessage(
            sender_id="history-chat-user",
            message_id="hello-message",
            type=MessageType.TEXT,
            text="你好",
        )

        response = await handler.handle(state, message)

        assert response == "你好，很高兴见到你。"
        assert "我要退款" in llm.prompt
        assert "请告诉我你的订单号" in llm.prompt
        assert "用户最后一句：你好" in llm.prompt

    asyncio.run(scenario())
