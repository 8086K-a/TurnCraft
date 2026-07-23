from typing import Any

from pydantic import BaseModel, Field

from .context import (
    TaskContext,
    SystemContext,
    FocusedObject,
)
from .session import Session
from .turn import Turn


class DialogueState(BaseModel):
    sender_id: str

    active_task: TaskContext | None = None

    paused_tasks: list[TaskContext] = Field(default_factory=list)

    active_system_flow: SystemContext | None = None

    focused_object: FocusedObject | None = None

    sessions: list[Session] = Field(default_factory=list)

    current_session_id: str | None = None

    pending_turn: Turn | None = None

    # Tracks returned by the planner while waiting for the user's choice.
    pending_clarification: list[dict[str, Any]] = Field(default_factory=list)

    def end_system_flow(self):
        self.active_system_flow = None

    def pause_active_task(self):
        self.paused_tasks.append(self.active_task)
        self.active_task = None

    def start_task(self, task_context: TaskContext):
        self.active_task = task_context

    def start_system_task(self, system_context: SystemContext):
        self.active_system_flow = system_context

    def set_slots(self, slots):
        self.active_task.slots.update(slots)

    def cancel_active_task(self):
        self.active_task = None

    def complete_active_task(self):
        self.active_task = None

    def resume_task(self, flow_id) -> TaskContext | None:
        for task in self.paused_tasks:
            if task.flow_id == flow_id:
                self.active_task = task
                self.paused_tasks.remove(task)
                return task
        return None

    def resume_latest_task(self) -> TaskContext | None:
        if not self.paused_tasks:
            return None
        self.active_task = self.paused_tasks.pop()
        return self.active_task
