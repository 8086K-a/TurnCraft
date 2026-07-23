import logging
import time
import uuid

from agent.domain.context import FocusedObject, ResumedSystemContext
from agent.domain.message import UserMessage, ProcessResult, BotMessage, MessageType
from agent.domain.dialogue_state import DialogueState
from agent.domain.session import Session
from agent.domain.turn import Turn
from agent.engine.turn_planner import TurnPlan
from agent.engine.turn_plan_validator import TurnPlanValidator
from agent.engine.workflow_trace import WorkflowTrace
from agent.handler.task.command.models import Command
from agent.handler.knowledge import handle_knowledge
from agent.handler.clarify import ClarifyResponder


MAX_STEPS_PER_TURN = 100
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
    ):
        self._task_handler = task_handler
        self._command_processor = command_processor
        self._flows_list = flows_list
        self._planner = planner
        self._plan_validator = plan_validator
        self._clarify_responder = clarify_responder or ClarifyResponder()
        self._api = api
        self._chitchat_handler = chitchat_handler
        self._trace: WorkflowTrace | None = None

    def set_task_components(self, handler, command_processor, flows_list):
        self._task_handler = handler
        self._command_processor = command_processor
        self._flows_list = flows_list

    async def process(self, state: DialogueState, user_message: UserMessage) -> ProcessResult:
        trace = WorkflowTrace()
        self._trace = trace
        self._prepare_session(state)
        turn = self._begin_turn(state, user_message)
        messages: list[BotMessage] = []
        trace.turn_start(user_message.sender_id, user_message.text, user_message.type.value)
        trace.state_full(state)
        try:
            if user_message.type == MessageType.TEXT:
                messages = await self._handle_text_message(state, user_message)
            else:
                messages = await self._handle_object_message(state, user_message)
        except Exception:
            logger.exception("Failed to process dialogue turn")
            trace.error("处理对话时发生异常")
            messages = [BotMessage(text="抱歉，这次请求没有处理成功，请稍后重试。")]

        turn.assistant_messages.extend(messages)
        self._finish_turn(state, turn)
        trace.state_full(state)
        trace.turn_end(len(messages))
        self._trace = None
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

    async def _handle_text_message(self, state: DialogueState, user_message: UserMessage):
        if not self._planner:
            raise RuntimeError("turn planner is not configured")
        try:
            plan = await self._next_plan(state, user_message)
            if self._plan_validator:
                plan = self._plan_validator.validate(plan)
            if self._trace:
                plan_dict = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else {}
                self._trace.plan(plan_dict)
        except (ValueError, TypeError):
            return [BotMessage(text=self._clarify_responder.respond("invalid_plan"))]
        return await self._route_plan(state, user_message, plan)

    async def _handle_object_message(self, state: DialogueState, user_message: UserMessage):
        if user_message.object is None:
            raise ValueError("object message is missing object payload")
        object_data = user_message.object
        state.focused_object = FocusedObject(
            type=object_data.type,
            id=object_data.id,
            title=object_data.title,
            attributes=object_data.attributes,
        )
        if self._trace:
            self._trace.track_selected("object_message")
            self._trace.command("set_slots", {"object_type": object_data.type, "object_id": object_data.id})
        command = self._object_slot_command(state, object_data.type, object_data.id, object_data.title)
        if command is not None:
            self._command_processor.run([command], state, self._flows_list)
            if self._trace:
                self._trace.state_full(state)
                self._trace.state_change(
                    active_task=state.active_task,
                    active_system_flow=state.active_system_flow,
                )
            return await self._run_task_track(state)
        if self._trace:
            self._trace.state_change(
                active_task=state.active_task,
                active_system_flow=state.active_system_flow,
            )
        return [
            BotMessage(
                text=self._clarify_responder.respond("object_intent", state.focused_object)
            )
        ]

    async def _route_plan(self, state: DialogueState, user_message: UserMessage, plan: TurnPlan):
        tracks = [(name, value) for name, value in (
            ("task", plan.task), ("knowledge", plan.knowledge), ("chitchat", plan.chitchat)
        ) if value is not None]
        if len(tracks) > 1:
            if self._trace:
                self._trace.track_selected("clarification_multiple")
            state.pending_clarification = [
                {"track": name, "value": value.model_dump(mode="json") if hasattr(value, "model_dump") else value}
                for name, value in tracks
            ]
            return [BotMessage(text=self._clarify_responder.respond("multiple_intents"))]
        state.pending_clarification = []
        if plan.task is not None:
            if self._trace:
                self._trace.track_selected("task")
            if not self._task_handler or not self._command_processor:
                raise RuntimeError("task components are not configured")
            commands = [Command.from_dict(item) for item in plan.task.commands]
            if self._trace:
                for cmd in commands:
                    cmd_dict = cmd.model_dump(exclude={"command"}, by_alias=True) if hasattr(cmd, "model_dump") else {}
                    self._trace.command(cmd.command, cmd_dict)
            self._command_processor.run(commands, state, self._flows_list)
            if self._trace:
                self._trace.state_full(state)
                self._trace.state_change(
                    active_task=state.active_task,
                    paused_tasks=state.paused_tasks,
                    active_system_flow=state.active_system_flow,
                )
            result = await self._run_task_track(state)
            return result or [BotMessage(text="当前没有可继续处理的任务。")]
        if plan.knowledge is not None:
            if self._trace:
                self._trace.track_selected("knowledge")
            if state.active_task:
                state.pause_active_task()
            intents = plan.knowledge.get("intents", [])
            if self._trace:
                self._trace.knowledge(intents)
                self._trace.state_change(
                    active_task=state.active_task,
                    paused_tasks=state.paused_tasks,
                )
            return [BotMessage(text=await handle_knowledge(intents, user_message.text or ""))]
        if plan.chitchat is not None:
            if self._trace:
                self._trace.track_selected("chitchat")
            if state.active_task:
                state.pause_active_task()
            if self._chitchat_handler is None:
                raise RuntimeError("chitchat handler is not configured")
            if self._trace:
                self._trace.chitchat()
                self._trace.state_change(
                    active_task=state.active_task,
                    paused_tasks=state.paused_tasks,
                )
            return [BotMessage(text=await self._chitchat_handler.handle(state, user_message))]
        if self._trace:
            self._trace.track_selected("unknown")
        return [BotMessage(text=self._clarify_responder.respond("unknown"))]

    def _object_slot_command(self, state, object_type, object_id, object_title):
        slot_name = None
        if state.active_system_flow:
            slot_name = getattr(state.active_system_flow, "slot_name", None)
        if not slot_name and state.active_task:
            step = self._flows_list.get_step(state.active_task.flow_id, state.active_task.step_id)
            if step and step.get("type") == "collect":
                slot_name = step.get("slot_name")
        mapped_slot = {"order": "order_number", "product": "product_id"}.get(object_type)
        if slot_name != mapped_slot:
            if object_type == "product" and slot_name == "course_name":
                mapped_slot = slot_name
            else:
                return None
        value = object_id if mapped_slot != "course_name" else (object_title or object_id)
        from agent.handler.task.command.models import SetSlotsCommand
        return SetSlotsCommand(command="set_slots", slots={mapped_slot: value})

    async def _next_plan(self, state: DialogueState, user_message: UserMessage):
        if not state.pending_clarification:
            return await self._planner.plan(state, user_message)
        selected = self._select_clarification(
            state.pending_clarification, user_message.text or ""
        )
        if selected is None:
            return await self._planner.plan(state, user_message)
        state.pending_clarification = []
        values = {"task": None, "knowledge": None, "chitchat": None}
        values[selected["track"]] = selected["value"]
        return TurnPlan.model_validate(values)

    @staticmethod
    def _select_clarification(options, text):
        normalized = text.strip().lower()
        if not normalized:
            return None
        index = None
        if normalized in {"1", "一", "第一个", "第一项", "第1个"}:
            index = 0
        elif normalized in {"2", "二", "第二个", "第二项", "第2个"}:
            index = 1
        elif normalized in {"3", "三", "第三个", "第三项", "第3个"}:
            index = 2
        if index is not None and index < len(options):
            return options[index]
        keywords = {
            "task": ("任务", "办理", "退款", "订单", "投诉", "工单", "报名"),
            "knowledge": ("咨询", "政策", "流程", "课程", "学习方式"),
            "chitchat": ("闲聊", "聊天", "问候", "打招呼"),
        }
        for option in options:
            if any(word in normalized for word in keywords.get(option["track"], ())):
                return option
        return None

    async def _run_task_track(self, state: DialogueState) -> list[BotMessage]:
        messages = await self._run_system_flow(state)

        for _ in range(MAX_STEPS_PER_TURN):
            if state.active_task is None:
                break

            task = state.active_task
            flow_id = task.flow_id
            step_id = task.step_id
            flow_name = ""
            flow = self._flows_list.get_flow_by_id(flow_id)
            if flow:
                flow_name = flow.name

            if self._trace:
                self._trace.flow_enter(flow_id, flow_name, "user")

            step = self._flows_list.get_step(flow_id, step_id)
            step_type = step.get("type", "unknown") if step else "unknown"
            step_desc = step.get("description", "") if step else ""

            if self._trace and step and step.get("type") == "action":
                act_name = step.get("action", "")
                self._trace.action_execute(flow_id, step_id, act_name, step.get("args", {}))

            if self._trace:
                self._trace.step_enter(flow_id, step_id, step_type, step_desc)

            result = await self._task_handler.step(
                flow_id,
                step_id,
                task.slots,
                context={
                    "user_id": state.sender_id,
                    "focused_object": (
                        state.focused_object.model_dump(mode="json")
                        if state.focused_object
                        else None
                    ),
                },
                api=self._api,
            )
            messages.extend(self._to_bot_messages(result.messages))
            task.slots.update(result.slots_updated)

            if self._trace:
                self._trace.step_result(flow_id, step_id, step_type,
                                         next_step_id=result.next_step_id,
                                         need_listen=result.need_listen,
                                         end_flow=result.end_flow,
                                         completed=result.completed)
                self._trace.state_full(state)
                if step and "next" in step:
                    self._trace_branches(flow_id, step_id, step, result.next_step_id, task.slots, {"user_id": state.sender_id})

            if result.end_flow or result.completed:
                state.complete_active_task()
                if self._trace:
                    self._trace.task_lifecycle("completed", flow_id, flow_name)
                    self._trace.state_full(state)
                    self._trace.state_change(
                        active_task=state.active_task,
                        paused_tasks=state.paused_tasks,
                        active_system_flow=state.active_system_flow,
                    )
                break
            if result.need_listen and result.next_step_id is None:
                break
            if result.next_step_id is None:
                break
            state.active_task.step_id = result.next_step_id
        else:
            raise RuntimeError("task flow exceeded the maximum number of steps")

        return messages

    async def _run_system_flow(self, state: DialogueState) -> list[BotMessage]:
        messages: list[BotMessage] = []
        for _ in range(MAX_STEPS_PER_TURN):
            system_flow = state.active_system_flow
            if system_flow is None:
                break
            flow_id = system_flow.flow_id
            step_id = system_flow.step_id
            if self._trace:
                self._trace.flow_enter(flow_id, flow_id, "system")
                self._trace.step_enter(flow_id, step_id, "system", "")
            context = system_flow.model_dump(exclude={"flow_id", "step_id"})
            result = await self._task_handler.step(
                flow_id,
                step_id,
                slots={},
                context=context,
            )
            messages.extend(self._to_bot_messages(result.messages))
            if self._trace:
                self._trace.step_result(flow_id, step_id, "system",
                                         next_step_id=result.next_step_id,
                                         end_flow=result.end_flow or result.completed)
            if result.end_flow or result.completed:
                state.end_system_flow()
                break
            if result.next_step_id is None:
                state.end_system_flow()
                break
            system_flow.step_id = result.next_step_id
        else:
            raise RuntimeError("system flow exceeded the maximum number of steps")
        return messages

    def _resume_latest_task(self, state: DialogueState) -> None:
        resumed = state.resume_latest_task()
        if resumed is None:
            return
        flow = self._flows_list.get_flow_by_id(resumed.flow_id)
        flow_name = flow.name if flow else resumed.flow_id
        state.start_system_task(
            ResumedSystemContext(
                flow_id="system_task_resumed",
                step_id="start",
                resumed_flow_id=resumed.flow_id,
                resumed_flow_name=flow_name,
            )
        )
        if self._trace:
            self._trace.task_lifecycle("resumed", resumed.flow_id, flow_name)
            self._trace.state_full(state)
            self._trace.state_change(
                active_task=state.active_task,
                paused_tasks=state.paused_tasks,
                active_system_flow=state.active_system_flow,
            )

    def _trace_branches(self, flow_id: str, step_id: str, step: dict, next_step_id: str | None, slots: dict, context: dict) -> None:
        from agent.handler.task.flow.renderer import evaluate_condition
        next_def = step.get("next")
        if not next_def or not self._trace:
            return
        if isinstance(next_def, list):
            for i, branch in enumerate(next_def):
                condition = branch.get("if", "")
                if "if" in branch:
                    taken = evaluate_condition(branch["if"], slots, context)
                    self._trace.branch(flow_id, step_id, i, condition, "taken" if taken else "skipped")
                elif "else" in branch:
                    self._trace.branch(flow_id, step_id, i, "else", "fallback")

    @staticmethod
    def _to_bot_messages(messages: list[dict]) -> list[BotMessage]:
        return [
            BotMessage(type=MessageType.TEXT, text=item.get("content") or item.get("text"))
            for item in messages
            if item.get("content") or item.get("text")
        ]

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
