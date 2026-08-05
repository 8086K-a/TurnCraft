from agent.domain.dialogue_state import DialogueState
from agent.domain.message import BotMessage, MessageType
from agent.engine.workflow_trace import WorkflowTrace
from agent.handler.task.flow.renderer import evaluate_condition


MAX_STEPS_PER_TURN = 100


class SystemFlowRunner:
    def __init__(self, task_handler):
        self._task_handler = task_handler

    async def run(self, state: DialogueState, trace: WorkflowTrace) -> list[BotMessage]:
        messages: list[BotMessage] = []
        traced_flows: set[str] = set()
        for _ in range(MAX_STEPS_PER_TURN):
            system_flow = state.active_system_flow
            if system_flow is None:
                break
            flow_id = system_flow.flow_id
            step_id = system_flow.step_id
            if flow_id not in traced_flows:
                trace.flow_enter(flow_id, flow_id, "system")
                traced_flows.add(flow_id)
            trace.step_enter(flow_id, step_id, "system", "")
            context = system_flow.model_dump(exclude={"flow_id", "step_id"})
            result = await self._task_handler.step(
                flow_id, step_id, slots={}, context=context
            )
            messages.extend(_to_bot_messages(result.messages))
            trace.step_result(
                flow_id,
                step_id,
                "system",
                next_step_id=result.next_step_id,
                end_flow=result.end_flow or result.completed,
            )
            if result.end_flow or result.completed or result.next_step_id is None:
                state.end_system_flow()
                break
            system_flow.step_id = result.next_step_id
        else:
            raise RuntimeError("system flow exceeded the maximum number of steps")
        return messages


class TaskRunner:
    def __init__(self, task_handler, flows_list, api=None, system_runner=None):
        self._task_handler = task_handler
        self._flows_list = flows_list
        self._api = api
        self._system_runner = system_runner or SystemFlowRunner(task_handler)

    async def run(self, state: DialogueState, trace: WorkflowTrace) -> list[BotMessage]:
        messages = await self._system_runner.run(state, trace)
        traced_flows: set[str] = set()

        for _ in range(MAX_STEPS_PER_TURN):
            if state.active_task is None:
                break
            task = state.active_task
            flow_id = task.flow_id
            step_id = task.step_id
            flow = self._flows_list.get_flow_by_id(flow_id)
            flow_name = flow.name if flow else ""

            if flow_id not in traced_flows:
                trace.flow_enter(flow_id, flow_name, "user")
                traced_flows.add(flow_id)

            step = self._flows_list.get_step(flow_id, step_id)
            step_type = step.get("type", "unknown") if step else "unknown"
            step_desc = step.get("description", "") if step else ""
            if step and step.get("type") == "action":
                trace.action_execute(
                    flow_id, step_id, step.get("action", ""), step.get("args", {})
                )
            trace.step_enter(flow_id, step_id, step_type, step_desc)

            context = {
                "user_id": state.sender_id,
                "focused_object": (
                    state.focused_object.model_dump(mode="json")
                    if state.focused_object
                    else None
                ),
            }
            result = await self._task_handler.step(
                flow_id,
                step_id,
                task.slots,
                context=context,
                api=self._api,
            )
            messages.extend(_to_bot_messages(result.messages))
            task.slots.update(result.slots_updated)
            if result.next_step_id is not None:
                task.step_id = result.next_step_id

            trace.step_result(
                flow_id,
                step_id,
                step_type,
                next_step_id=result.next_step_id,
                need_listen=result.need_listen,
                end_flow=result.end_flow,
                completed=result.completed,
            )
            trace.state_full(state)
            self._trace_branches(
                trace, flow_id, step_id, step, result.next_step_id, task.slots, context
            )

            if result.end_flow or result.completed:
                state.complete_active_task()
                trace.task_lifecycle("completed", flow_id, flow_name)
                trace.state_full(state)
                trace.state_change(
                    active_task=state.active_task,
                    paused_tasks=state.paused_tasks,
                    active_system_flow=state.active_system_flow,
                )
                break
            if result.need_listen or result.next_step_id is None:
                break
        else:
            raise RuntimeError("task flow exceeded the maximum number of steps")
        return messages

    @staticmethod
    def _trace_branches(trace, flow_id, step_id, step, next_step_id, slots, context):
        if not step or "next" not in step or not isinstance(step.get("next"), list):
            return
        for index, branch in enumerate(step["next"]):
            condition = branch.get("if", "")
            if "if" in branch:
                taken = evaluate_condition(branch["if"], slots, context)
                trace.branch(
                    flow_id, step_id, index, condition, "taken" if taken else "skipped"
                )
            elif "else" in branch:
                trace.branch(flow_id, step_id, index, "else", "fallback")


def _to_bot_messages(messages: list[dict]) -> list[BotMessage]:
    return [
        BotMessage(type=MessageType.TEXT, text=item.get("content") or item.get("text"))
        for item in messages
        if item.get("content") or item.get("text")
    ]
