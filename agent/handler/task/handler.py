from ..task.action import ActionExecutor
from ..task.flow import FlowManager
from .models import TaskStepResult


class TaskHandler:
    def __init__(self, flow_manager: FlowManager, action_executor: ActionExecutor):
        self._fm = flow_manager
        self._ae = action_executor

    async def step(
        self,
        flow_id: str,
        step_id: str,
        slots: dict,
        context: dict | None = None,
        **action_kwargs,
    ) -> TaskStepResult:
        step = self._fm.get_step(flow_id, step_id)
        if not step:
            return TaskStepResult(completed=True)

        ctx = context or {}
        step_type = step["type"]

        if step_type == "start":
            next_id = self._fm.resolve_next(step, slots, ctx)
            return TaskStepResult(next_step_id=next_id)

        if step_type == "collect":
            slot_name = step.get("slot_name")
            if slot_name and slot_name in slots and slots[slot_name] is not None:
                next_id = self._fm.resolve_next(step, slots, ctx)
                return TaskStepResult(next_step_id=next_id)
            response = step.get("response", {})
            rendered = self._fm.render(response, slots, ctx)
            return TaskStepResult(
                need_listen=True,
                messages=[{"role": "assistant", "content": rendered.get("text", "")}],
                slots_updated={},
            )

        if step_type == "action":
            return await self._handle_action_step(step, slots, ctx, **action_kwargs)

        if step_type == "end":
            return TaskStepResult(end_flow=True)

        return TaskStepResult(completed=True)

    async def _handle_action_step(
        self,
        step: dict,
        slots: dict,
        context: dict,
        **action_kwargs,
    ) -> TaskStepResult:
        action_name = step.get("action")
        args = step.get("args", {})
        rendered_args = self._fm.render(args, slots, context)

        if self._ae.has(action_name):
            result = await self._ae.execute(
                action_name,
                rendered_args,
                slots,
                context,
                **action_kwargs,
            )
        else:
            return TaskStepResult(
                messages=[{"role": "assistant", "content": "任务配置错误，暂时无法继续处理。"}],
                end_flow=True,
            )

        merged_slots = {**slots, **result.slots}
        next_id = self._fm.resolve_next(step, merged_slots, context)

        return TaskStepResult(
            next_step_id=next_id,
            messages=result.messages,
            need_listen=result.need_listen,
            slots_updated=result.slots,
            end_flow=result.end_flow,
        )
