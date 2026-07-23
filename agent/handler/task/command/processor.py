from agent.domain.context import (
    TaskContext,
    StartedSystemContext,
    InterruptedSystemContext,
    CanceledSystemContext,
    ResumedSystemContext,
)
from agent.domain.dialogue_state import DialogueState
from agent.handler.task.command.models import (
    Command,
    StartFlowCommand,
    SetSlotsCommand,
    CancelFlowCommand,
    ResumeFlowCommand,
)
from agent.handler.task.flow.models import FlowsList


class CommandProcessor:
    def run(self, commands: list[Command], state: DialogueState, flows: FlowsList) -> None:
        commands = self._merge_commands(commands)
        for command in commands:
            self._apply(command, state, flows)

    @staticmethod
    def _merge_commands(commands: list[Command]) -> list[Command]:
        merged = []
        skip_next = False
        for i, cmd in enumerate(commands):
            if skip_next:
                skip_next = False
                continue
            if isinstance(cmd, CancelFlowCommand) and i + 1 < len(commands) and isinstance(commands[i + 1], StartFlowCommand):
                merged.append(commands[i + 1])
                skip_next = True
            else:
                merged.append(cmd)
        return merged

    def _apply(self, command: Command, state: DialogueState, flows: FlowsList) -> None:
        if isinstance(command, StartFlowCommand):
            self._handle_start_flow(command, state, flows)
        elif isinstance(command, SetSlotsCommand):
            self._handle_set_slots(command, state)
        elif isinstance(command, CancelFlowCommand):
            self._handle_cancel_flow(state, flows)
        elif isinstance(command, ResumeFlowCommand):
            self._handle_resume_flow(command, state, flows)

    @staticmethod
    def _handle_start_flow(command: StartFlowCommand, state: DialogueState, flows: FlowsList) -> None:
        target_flow = flows.get_flow_by_id(command.flow)
        if not target_flow:
            return

        active_task = state.active_task
        if active_task and active_task.flow_id == target_flow.id:
            return

        state.end_system_flow()
        if active_task:
            state.pause_active_task()
            state.start_task(TaskContext(flow_id=target_flow.id, step_id="start"))
            state.start_system_task(InterruptedSystemContext(
                flow_id="system_task_interrupted",
                step_id="start",
                started_flow_id=target_flow.id,
                started_flow_name=target_flow.name,
                interrupted_flow_id=active_task.flow_id,
                interrupted_flow_name=flows.get_flow_by_id(active_task.flow_id).name,
            ))
        else:
            state.start_task(TaskContext(flow_id=target_flow.id, step_id="start"))
            state.start_system_task(StartedSystemContext(
                flow_id="system_task_started",
                step_id="start",
                started_flow_id=target_flow.id,
                started_flow_name=target_flow.name,
            ))

    @staticmethod
    def _handle_set_slots(command: SetSlotsCommand, state: DialogueState) -> None:
        if state.active_task:
            state.set_slots(command.slots)

    @staticmethod
    def _handle_cancel_flow(state: DialogueState, flows: FlowsList) -> None:
        active_task = state.active_task
        if not active_task:
            return
        target_flow = flows.get_flow_by_id(active_task.flow_id)
        state.cancel_active_task()
        state.start_system_task(CanceledSystemContext(
            flow_id="system_task_canceled",
            step_id="start",
            canceled_flow_id=target_flow.id,
            canceled_flow_name=target_flow.name,
        ))

    @staticmethod
    def _handle_resume_flow(command: ResumeFlowCommand, state: DialogueState, flows: FlowsList) -> None:
        target_flow = flows.get_flow_by_id(command.flow)
        paused_flow_ids = {task.flow_id for task in state.paused_tasks}
        if not target_flow or target_flow.id not in paused_flow_ids:
            return
        active_task = state.active_task
        if active_task:
            state.pause_active_task()
            resumed = state.resume_task(target_flow.id)
            if resumed is None:
                return
            state.start_system_task(InterruptedSystemContext(
                flow_id="system_task_interrupted",
                step_id="start",
                interrupted_flow_id=active_task.flow_id,
                interrupted_flow_name=flows.get_flow_by_id(active_task.flow_id).name,
                started_flow_id=target_flow.id,
                started_flow_name=target_flow.name,
            ))
        else:
            resumed = state.resume_task(target_flow.id)
            if resumed is None:
                return
            state.start_system_task(ResumedSystemContext(
                flow_id="system_task_resumed",
                step_id="start",
                resumed_flow_id=target_flow.id,
                resumed_flow_name=target_flow.name,
            ))
