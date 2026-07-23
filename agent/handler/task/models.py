from typing import Any

from pydantic import BaseModel, Field


class TaskStepResult(BaseModel):
    completed: bool = False
    next_step_id: str | None = None
    messages: list[dict] = Field(default_factory=list)
    need_listen: bool = False
    slots_updated: dict[str, Any] = Field(default_factory=dict)
    end_flow: bool = False

    @property
    def should_advance(self) -> bool:
        return self.next_step_id is not None and not self.need_listen and not self.end_flow
