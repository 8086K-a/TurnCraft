from typing import Any, Callable, Awaitable

from pydantic import BaseModel, Field


class ActionResult(BaseModel):
    messages: list[dict] = Field(default_factory=list)
    slots: dict[str, Any] = Field(default_factory=dict)
    need_listen: bool = False
    end_flow: bool = False


ActionFn = Callable[..., Awaitable[ActionResult] | ActionResult]
