import json
import sys
import time
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field


class EventData(BaseModel):
    timestamp: float = Field(default_factory=time.time)


class TurnStartEvent(EventData):
    event: str = "turn_start"
    sender_id: str
    message_text: str | None = None
    message_type: str


class PlanEvent(EventData):
    event: str = "plan"
    plan: dict[str, Any]


class TrackSelectedEvent(EventData):
    event: str = "track_selected"
    track: str


class RoutingEvent(EventData):
    event: str = "routing"
    problem_type: str | None = None
    decision: str
    channel: str = ""
    skip_llm: bool = False
    cache_hit: bool = False
    cancel_flow: bool = False
    selected_tools: list[dict] = Field(default_factory=list)
    alternatives: list[dict] = Field(default_factory=list)
    missing_parameters: list[str] = Field(default_factory=list)


class CommandEvent(EventData):
    event: str = "command"
    command_name: str
    details: dict[str, Any]


class StateChangeEvent(EventData):
    event: str = "state_change"
    active_task: dict[str, Any] | None = None
    paused_tasks: list[dict[str, Any]] = Field(default_factory=list)
    active_system_flow: dict[str, Any] | None = None


class FlowEnterEvent(EventData):
    event: str = "flow_enter"
    flow_id: str
    flow_name: str
    flow_type: str  # user / system


class StepEnterEvent(EventData):
    event: str = "step_enter"
    flow_id: str
    step_id: str
    step_type: str
    description: str = ""


class BranchEvent(EventData):
    event: str = "branch"
    flow_id: str
    step_id: str
    branch_index: int
    condition: str = ""
    result: str  # taken / skipped / fallback


class ActionExecuteEvent(EventData):
    event: str = "action_execute"
    flow_id: str
    step_id: str
    action_name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ActionResultEvent(EventData):
    event: str = "action_result"
    flow_id: str
    step_id: str
    action_name: str
    next_step_id: str | None = None
    need_listen: bool = False
    end_flow: bool = False
    slots_updated: dict[str, Any] = Field(default_factory=dict)


class StepResultEvent(EventData):
    event: str = "step_result"
    flow_id: str
    step_id: str
    step_type: str
    next_step_id: str | None = None
    need_listen: bool = False
    end_flow: bool = False
    completed: bool = False


class TaskLifecycleEvent(EventData):
    event: str = "task_lifecycle"
    action: str  # started / paused / resumed / completed / canceled
    flow_id: str
    flow_name: str = ""


class KnowledgeEvent(EventData):
    event: str = "knowledge"
    intents: list[str]


class ChitchatEvent(EventData):
    event: str = "chitchat"


class TurnEndEvent(EventData):
    event: str = "turn_end"
    message_count: int


class StateFullEvent(EventData):
    event: str = "state_full"
    state: dict[str, Any]


class ErrorEvent(EventData):
    event: str = "error"
    message: str


TraceEvent = (
    TurnStartEvent
    | PlanEvent
    | TrackSelectedEvent
    | RoutingEvent
    | CommandEvent
    | StateChangeEvent
    | StateFullEvent
    | FlowEnterEvent
    | StepEnterEvent
    | BranchEvent
    | ActionExecuteEvent
    | ActionResultEvent
    | StepResultEvent
    | TaskLifecycleEvent
    | KnowledgeEvent
    | ChitchatEvent
    | TurnEndEvent
    | ErrorEvent
)


logger.remove()
logger.add(
    "logs/trace.log",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
    level="TRACE",
    rotation="50 MB",
    retention=7,
)
logger.add(
    sys.stderr,
    format="{time:HH:mm:ss.SSS} | {level:<7} | {message}",
    level="WARNING",
)

class WorkflowTrace(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)

    def _add(self, event: TraceEvent) -> None:
        dumped = event.model_dump(mode="json")
        self.events.append(dumped)
        logger.trace(json.dumps(dumped, ensure_ascii=False))

    def turn_start(self, sender_id: str, text: str | None, msg_type: str) -> None:
        self._add(TurnStartEvent(sender_id=sender_id, message_text=text, message_type=msg_type))

    def plan(self, plan: dict[str, Any]) -> None:
        self._add(PlanEvent(plan=plan))

    def track_selected(self, track: str) -> None:
        self._add(TrackSelectedEvent(track=track))

    def routing(self, result: Any) -> None:
        self._add(RoutingEvent(
            problem_type=(
                result.problem_type.value if result.problem_type else None
            ),
            decision=result.decision.value,
            channel=result.channel,
            skip_llm=result.skip_llm,
            cache_hit=result.cache_hit,
            cancel_flow=result.cancel_flow,
            selected_tools=[
                {"name": c.name, "final_score": round(c.final_score, 4)}
                for c in result.selected_tools
            ],
            alternatives=[
                {"name": c.name, "final_score": round(c.final_score, 4)}
                for c in result.alternatives
            ],
            missing_parameters=list(result.missing_parameters),
        ))

    def command(self, command_name: str, details: dict[str, Any]) -> None:
        self._add(CommandEvent(command_name=command_name, details=details))

    def state_change(
        self,
        active_task: Any | None = None,
        paused_tasks: list[Any] | None = None,
        active_system_flow: Any | None = None,
    ) -> None:
        self._add(StateChangeEvent(
            active_task=self._dump(active_task),
            paused_tasks=[self._dump(t) for t in (paused_tasks or [])],
            active_system_flow=self._dump(active_system_flow),
        ))

    def flow_enter(self, flow_id: str, flow_name: str, flow_type: str = "user") -> None:
        self._add(FlowEnterEvent(flow_id=flow_id, flow_name=flow_name, flow_type=flow_type))

    def step_enter(self, flow_id: str, step_id: str, step_type: str, description: str = "") -> None:
        self._add(StepEnterEvent(flow_id=flow_id, step_id=step_id, step_type=step_type, description=description))

    def branch(self, flow_id: str, step_id: str, branch_index: int, condition: str, result: str) -> None:
        self._add(BranchEvent(flow_id=flow_id, step_id=step_id, branch_index=branch_index, condition=condition, result=result))

    def action_execute(self, flow_id: str, step_id: str, action_name: str, args: dict[str, Any]) -> None:
        self._add(ActionExecuteEvent(flow_id=flow_id, step_id=step_id, action_name=action_name, args=args))

    def action_result(self, flow_id: str, step_id: str, action_name: str, next_step_id: str | None = None,
                       need_listen: bool = False, end_flow: bool = False, slots_updated: dict | None = None) -> None:
        self._add(ActionResultEvent(
            flow_id=flow_id, step_id=step_id, action_name=action_name,
            next_step_id=next_step_id, need_listen=need_listen,
            end_flow=end_flow, slots_updated=slots_updated or {},
        ))

    def step_result(self, flow_id: str, step_id: str, step_type: str,
                     next_step_id: str | None = None, need_listen: bool = False,
                     end_flow: bool = False, completed: bool = False) -> None:
        self._add(StepResultEvent(
            flow_id=flow_id, step_id=step_id, step_type=step_type,
            next_step_id=next_step_id, need_listen=need_listen,
            end_flow=end_flow, completed=completed,
        ))

    def task_lifecycle(self, action: str, flow_id: str, flow_name: str = "") -> None:
        self._add(TaskLifecycleEvent(action=action, flow_id=flow_id, flow_name=flow_name))

    def knowledge(self, intents: list[str]) -> None:
        self._add(KnowledgeEvent(intents=intents))

    def chitchat(self) -> None:
        self._add(ChitchatEvent())

    def turn_end(self, message_count: int) -> None:
        self._add(TurnEndEvent(message_count=message_count))

    def state_full(self, state: Any) -> None:
        state_dict = self._dump(state)
        if state_dict is not None:
            self._add(StateFullEvent(state=state_dict))

    def error(self, message: str) -> None:
        self._add(ErrorEvent(message=message))

    @staticmethod
    def _dump(obj: Any) -> Any:
        if obj is None:
            return None
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        return str(obj)
