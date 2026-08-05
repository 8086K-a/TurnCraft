from agent.domain.dialogue_state import DialogueState
from agent.domain.message import BotMessage, UserMessage
from agent.engine.turn_planner import TurnPlan
from agent.handler.knowledge import KnowledgeHandler
from agent.handler.task.command.models import Command
from agent.prompts.history_builder import HistoryBuilder


class PlanRouter:
    def __init__(
        self,
        command_processor,
        flows_list,
        task_runner,
        clarify_responder,
        chitchat_handler=None,
        knowledge_handler=None,
    ):
        self._command_processor = command_processor
        self._flows_list = flows_list
        self._task_runner = task_runner
        self._clarify_responder = clarify_responder
        self._chitchat_handler = chitchat_handler
        self._knowledge_handler = knowledge_handler or KnowledgeHandler()

    async def route(self, state, user_message, plan: TurnPlan, trace):
        tracks = [
            (name, value)
            for name, value in (
                ("task", plan.task),
                ("knowledge", plan.knowledge),
                ("chitchat", plan.chitchat),
            )
            if value is not None
        ]
        if len(tracks) > 1:
            trace.track_selected("clarification_multiple")
            return [BotMessage(text=await self._clarify("multiple_intents", state, user_message))]
        if plan.task is not None:
            return await self._route_task(state, plan, trace)
        if plan.knowledge is not None:
            return await self._route_knowledge(state, user_message, plan, trace)
        if plan.chitchat is not None:
            return await self._route_chitchat(state, user_message, trace)
        trace.track_selected("unknown")
        return [BotMessage(text=await self._clarify("unknown", state, user_message))]

    async def _route_task(self, state, plan, trace):
        trace.track_selected("task")
        if not self._command_processor or not self._task_runner:
            raise RuntimeError("task components are not configured")
        commands = [Command.from_dict(item) for item in plan.task.commands]
        for command in commands:
            details = command.model_dump(exclude={"command"}, by_alias=True)
            trace.command(command.command, details)
        self._command_processor.run(commands, state, self._flows_list)
        trace.state_full(state)
        trace.state_change(
            active_task=state.active_task,
            paused_tasks=state.paused_tasks,
            active_system_flow=state.active_system_flow,
        )
        result = await self._task_runner.run(state, trace)
        return result or [BotMessage(text="当前没有可继续处理的任务。")]

    async def _route_knowledge(self, state, user_message, plan, trace):
        trace.track_selected("knowledge")
        if state.active_task:
            state.pause_active_task()
        intents = plan.knowledge.get("intents", [])
        trace.knowledge(intents)
        trace.state_change(active_task=state.active_task, paused_tasks=state.paused_tasks)
        text = await self._knowledge_handler.handle(
            intents, user_message.text or "", history=self._history(state)
        )
        return [BotMessage(text=text)]

    async def _route_chitchat(self, state, user_message, trace):
        trace.track_selected("chitchat")
        if state.active_task:
            state.pause_active_task()
        if self._chitchat_handler is None:
            raise RuntimeError("chitchat handler is not configured")
        trace.chitchat()
        trace.state_change(active_task=state.active_task, paused_tasks=state.paused_tasks)
        return [BotMessage(text=await self._chitchat_handler.handle(state, user_message))]

    async def _clarify(self, reason, state, user_message):
        return await self._clarify_responder.respond(
            reason, user_message=user_message, history=self._history(state)
        )

    @staticmethod
    def _history(state: DialogueState) -> str:
        if not state.current_session_id:
            return ""
        session = next(
            (item for item in state.sessions if item.session_id == state.current_session_id),
            None,
        )
        return HistoryBuilder.build(session.turns) if session else ""
