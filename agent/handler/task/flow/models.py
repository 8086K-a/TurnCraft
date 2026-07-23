from ..flow import FlowManager


class FlowSlot:
    def __init__(self, name: str, **kwargs):
        self.name = name
        for k, v in kwargs.items():
            setattr(self, k, v)


class FlowStep:
    def __init__(self, data: dict):
        self._data = data

    @property
    def id(self) -> str:
        return self._data["id"]


class Flow:
    def __init__(self, flow_id: str, data: dict, manager: FlowManager):
        self.id = flow_id
        self.name = data.get("name", flow_id)
        self.description = data.get("description", "")
        self._data = data
        self._manager = manager

    def get_start_step(self) -> FlowStep:
        step = self._manager.get_step(self.id, "start")
        return FlowStep(step) if step else None

    def start_step(self) -> FlowStep:
        return self.get_start_step()


class FlowsList:
    def __init__(self, manager: FlowManager):
        self._manager = manager

    def get_flow_by_id(self, flow_id: str) -> Flow | None:
        data = self._manager.get_flow(flow_id)
        if not data:
            return None
        return Flow(flow_id, data, self._manager)

    def get_step(self, flow_id: str, step_id: str) -> dict | None:
        return self._manager.get_step(flow_id, step_id)

    @property
    def flows(self) -> list[Flow]:
        return [
            flow
            for flow_id in self._manager.get_all_flow_ids()
            if (flow := self.get_flow_by_id(flow_id)) is not None
        ]

    @property
    def slots(self) -> dict[str, FlowSlot]:
        return {
            name: FlowSlot(name=name, **definition)
            for name, definition in self._manager.get_slot_definitions().items()
        }
