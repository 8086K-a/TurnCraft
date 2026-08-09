import logging
import time
import uuid

from agent.domain.context import FocusedObject
from agent.domain.message import UserMessage, ProcessResult, BotMessage, MessageType
from agent.domain.dialogue_state import DialogueState
from agent.domain.session import Session
from agent.domain.turn import Turn
from agent.engine.plan_router import PlanRouter
from agent.engine.task_runner import TaskRunner
from agent.engine.workflow_trace import WorkflowTrace
from agent.handler.clarify import ClarifyResponder


SESSION_TIMEOUT_SECONDS = 60 * 60
logger = logging.getLogger(__name__)


class DialogueEngine:
    def __init__(
        self,
        task_handler=None,
        command_processor=None,
        flows_list=None,
        planner=None,
        plan_validator=None,
        clarify_responder=None,
        api=None,
        chitchat_handler=None,
        knowledge_handler=None,
    ):
        self._task_handler = task_handler
        self._command_processor = command_processor
        self._flows_list = flows_list
        self._planner = planner
        self._plan_validator = plan_validator
        self._clarify_responder = clarify_responder or ClarifyResponder()
        self._api = api
        self._knowledge_handler = knowledge_handler
        self._chitchat_handler = chitchat_handler
        self._build_runtime_components()

    def set_task_components(self, handler, command_processor, flows_list):
        self._task_handler = handler
        self._command_processor = command_processor
        self._flows_list = flows_list
        self._build_runtime_components()

    def _build_runtime_components(self):
        self._task_runner = (
            TaskRunner(self._task_handler, self._flows_list, self._api)
            if self._task_handler and self._flows_list
            else None
        )
        self._plan_router = PlanRouter(
            command_processor=self._command_processor,
            flows_list=self._flows_list,
            task_runner=self._task_runner,
            clarify_responder=self._clarify_responder,
            chitchat_handler=self._chitchat_handler,
            knowledge_handler=self._knowledge_handler,
        )

    async def process(self, state: DialogueState, user_message: UserMessage) -> ProcessResult:
        trace = WorkflowTrace()
        self._prepare_session(state)
        turn = self._begin_turn(state, user_message)
        messages: list[BotMessage] = []
        trace.turn_start(user_message.sender_id, user_message.text, user_message.type.value)
        trace.state_full(state)
        try:
            if user_message.type == MessageType.TEXT:
                messages = await self._handle_text_message(state, user_message, trace)
            else:
                messages = await self._handle_object_message(state, user_message, trace)
        except Exception:
            logger.exception("Failed to process dialogue turn")
            trace.error("处理对话时发生异常")
            messages = [BotMessage(text="抱歉，这次请求没有处理成功，请稍后重试。")]

        turn.assistant_messages.extend(messages)
        self._finish_turn(state, turn)
        trace.state_full(state)
        trace.turn_end(len(messages))
        return ProcessResult(
            sender_id=user_message.sender_id,
            message_id=user_message.message_id,
            messages=messages,
            trace=trace.events,
        )

    def _prepare_session(self, state: DialogueState) -> None:
        now = time.time()
        if not state.current_session_id:
            return
        session = next(
            (item for item in state.sessions if item.session_id == state.current_session_id),
            None,
        )
        if session and now - session.last_activity_at >= SESSION_TIMEOUT_SECONDS:
            session.closed_at = now
            state.current_session_id = None
            state.active_task = None
            state.paused_tasks = []
            state.active_system_flow = None
            state.focused_object = None

    async def _handle_text_message(self, state, user_message, trace):
        if not self._planner:
            raise RuntimeError("turn planner is not configured")
        try:
            plan = await self._next_plan(state, user_message)
            if self._plan_validator:
                plan = self._plan_validator.validate(plan)
            plan_dict = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else {}
            trace.plan(plan_dict)
            last_result = getattr(self._planner, "last_result", None)
            if last_result is not None:
                trace.routing(last_result)
        except (ValueError, TypeError):
            text = await self._clarify_responder.respond("invalid_plan", user_message=user_message, history=self._history(state))
            return [BotMessage(text=text)]
        return await self._plan_router.route(state, user_message, plan, trace)

    async def _handle_object_message(self, state, user_message, trace):
        if user_message.object is None:
            raise ValueError("object message is missing object payload")
        object_data = user_message.object
        state.focused_object = FocusedObject(
            type=object_data.type,
            id=object_data.id,
            title=object_data.title,
            attributes=object_data.attributes,
        )
        trace.track_selected("object_message")
        trace.command("set_slots", {"object_type": object_data.type, "object_id": object_data.id})
        command = self._object_slot_command(state, object_data.type, object_data.id, object_data.title)
        if command is not None:
            self._command_processor.run([command], state, self._flows_list)
            trace.state_full(state)
            trace.state_change(
                active_task=state.active_task,
                active_system_flow=state.active_system_flow,
            )
            return await self._task_runner.run(state, trace)
        trace.state_change(
            active_task=state.active_task,
            active_system_flow=state.active_system_flow,
        )
        text = await self._clarify_responder.respond("object_intent", state.focused_object, user_message=user_message, history=self._history(state))
        return [BotMessage(text=text)]

    def _object_slot_command(self, state, object_type, object_id, object_title):
        slot_name = None
        if state.active_system_flow:
            slot_name = getattr(state.active_system_flow, "slot_name", None)
        if not slot_name and state.active_task:
            step = self._flows_list.get_step(state.active_task.flow_id, state.active_task.step_id)
            if step and step.get("type") == "collect":
                slot_name = step.get("slot_name")
        mapped_slot = {"order": "order_number", "product": "product_id", "course": "course_name", "cohort": "cohort_name"}.get(object_type)
        if mapped_slot is None:
            return None
        if slot_name != mapped_slot:
            if object_type == "product" and slot_name == "course_name":
                mapped_slot = slot_name
            else:
                return None
        value = object_id if mapped_slot not in ("course_name", "cohort_name") else (object_title or object_id)
        from agent.handler.task.command.models import SetSlotsCommand
        return SetSlotsCommand(command="set_slots", slots={mapped_slot: value})

    async def _next_plan(self, state: DialogueState, user_message: UserMessage):
        return await self._planner.plan(state, user_message)

    @staticmethod
    def _begin_turn(state: DialogueState, user_message: UserMessage) -> Turn:
        now = time.time()
        if state.current_session_id is None:
            session = Session(
                session_id=str(uuid.uuid4()),
                started_at=now,
                last_activity_at=now,
            )
            state.sessions.append(session)
            state.current_session_id = session.session_id
        turn = Turn(
            turn_id=str(uuid.uuid4()),
            input_message=user_message,
        )
        state.pending_turn = turn
        return turn

    @staticmethod
    def _finish_turn(state: DialogueState, turn: Turn) -> None:
        session = next(
            item for item in state.sessions if item.session_id == state.current_session_id
        )
        session.turns.append(turn)
        session.last_activity_at = time.time()
        state.pending_turn = None

    @staticmethod
    def _history(state: DialogueState) -> str:
        if not state.current_session_id:
            return ""
        session = next(
            (item for item in state.sessions if item.session_id == state.current_session_id),
            None,
        )
        if not session:
            return ""
        from agent.prompts.history_builder import HistoryBuilder
        return HistoryBuilder.build(session.turns)
