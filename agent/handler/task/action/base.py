from abc import ABC, abstractmethod
from dataclasses import field
from typing import Any
from pydantic import BaseModel
from agent.domain.dialogue_state import DialogueState
from agent.domain.message import BotMessage



class ActionResult(BaseModel):
    messages: list[BotMessage] = field(default_factory=list)
    slot_updates: dict[str, Any] = field(default_factory=dict)


class Action(ABC):
    name: str

    @abstractmethod
    async def run(
            self,
            state: DialogueState,
            action_kwargs: dict[str, Any],
    ) -> ActionResult:
        pass
