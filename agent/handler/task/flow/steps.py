from pydantic import BaseModel, Field
from enum import Enum
from typing import List, Any

from .links import FlowStepLink, StaticLink, ConditionalLink, FallbackLink


class FlowStepType(Enum):
    START = "start"
    ACTION = "action"
    COLLECT = "collect"
    END = "end"


class ResponseDefinition(BaseModel):
    mode: str = "static"
    text: str | None = None
    prompt: str | None = None


class SlotValidation(BaseModel):
    condition: str | None = None
    failure_response: ResponseDefinition | None = None


class FlowStep(BaseModel):
    id: str
    type: FlowStepType
    next: List[FlowStepLink] = Field(default_factory=list)
    description: str = ""

    @classmethod
    def from_dict(cls, step_data: dict[str, Any]) -> "FlowStep":
        step_type = step_data["type"]
        clz = STEP_TYPE_TO_CLASS[step_type]
        data = dict(step_data)
        data["type"] = FlowStepType(data["type"])
        data["next"] = cls.build_links(data["next"])
        return clz.model_validate(data)

    @staticmethod
    def build_links(next_data: str | list) -> list[FlowStepLink]:
        if isinstance(next_data, str):
            return [StaticLink(target=next_data)]
        else:
            links = []
            for link_data in next_data:
                if "if" in link_data:
                    links.append(
                        ConditionalLink(
                            target=link_data["then"], condition=link_data["if"]
                        )
                    )
                else:
                    links.append(FallbackLink(target=link_data["else"]))
            return links


class StartFlowStep(FlowStep):
    pass


class ActionFlowStep(FlowStep):
    action: str = ""
    args: str | dict[str, Any] = Field(default_factory=dict)


class CollectSlotStep(FlowStep):
    slot_name: str = ""
    response: ResponseDefinition = Field(default_factory=ResponseDefinition)
    validation: SlotValidation | None = None


class EndFlowStep(FlowStep):
    pass


STEP_TYPE_TO_CLASS = {
    "start": StartFlowStep,
    "action": ActionFlowStep,
    "collect": CollectSlotStep,
    "end": EndFlowStep,
}
