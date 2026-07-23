from pydantic import BaseModel, Field
from typing import Any


class TaskContext(BaseModel):
    flow_id: str
    step_id: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)


class SystemContext(BaseModel):
    flow_id: str
    step_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SystemContext":
        clz = FLOW_ID_TO_CONTEXT_CLASS[data["flow_id"]]
        return clz.model_validate(data)


class FocusedObject(BaseModel):
    type: str
    id: str
    title: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class StartedSystemContext(SystemContext):
    started_flow_id: str = ""
    started_flow_name: str = ""


class InterruptedSystemContext(SystemContext):
    interrupted_flow_id: str = ""
    interrupted_flow_name: str = ""
    started_flow_id: str = ""
    started_flow_name: str = ""


class CanceledSystemContext(SystemContext):
    canceled_flow_id: str = ""
    canceled_flow_name: str = ""


class ResumedSystemContext(SystemContext):
    resumed_flow_id: str = ""
    resumed_flow_name: str = ""


class CollectSystemContext(SystemContext):
    slot_name: str = ""
    response: dict[str, Any] = Field(default_factory=dict)

#工厂模式,根据flow的名字返回对应的context
FLOW_ID_TO_CONTEXT_CLASS = {
    "system_task_started": StartedSystemContext,
    "system_task_interrupted": InterruptedSystemContext,
    "system_task_canceled": CanceledSystemContext,
    "system_task_resumed": ResumedSystemContext,
    "system_collect_information": CollectSystemContext,
}
