from pathlib import Path
from typing import Any

import yaml

from .renderer import render_value, evaluate_condition


class FlowManager:
    def __init__(self):
        self._user_flows: dict[str, dict] = {}
        self._system_flows: dict[str, dict] = {}
        self._user_slot_defs: dict[str, dict] = {}

    def load_from_dir(self, config_dir: str):
        config_path = Path(config_dir)
        self.load_many(
            [config_path / "user_flows.yml", config_path / "system_flows.yml"]
        )

    def load_many(self, paths: list[Path]) -> None:
        for path in paths:
            if not path.exists():
                continue
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            flows = data.get("flows", {})
            if "slots" in data:
                self._user_slot_defs.update(data.get("slots", {}))
                self._user_flows.update(flows)
            else:
                self._system_flows.update(flows)

    def get_flow(self, flow_id: str) -> dict | None:
        return self._user_flows.get(flow_id) or self._system_flows.get(flow_id)

    def get_step(self, flow_id: str, step_id: str) -> dict | None:
        flow = self.get_flow(flow_id)
        if not flow:
            return None
        for step in flow.get("steps", []):
            if step["id"] == step_id:
                return step
        return None

    def get_start_step(self, flow_id: str) -> dict | None:
        return self.get_step(flow_id, "start")

    def resolve_next(self, step: dict, slots: dict, context: dict) -> str | None:
        next_def = step.get("next")
        if next_def is None:
            return None
        if isinstance(next_def, str):
            return next_def
        if isinstance(next_def, list):
            for branch in next_def:
                if "if" in branch:
                    if evaluate_condition(branch["if"], slots, context):
                        return branch["then"]
                elif "else" in branch:
                    return branch["else"]
            return None
        return None

    def render(self, value: Any, slots: dict, context: dict) -> Any:
        return render_value(value, slots, context)

    def is_system_flow(self, flow_id: str) -> bool:
        return flow_id in self._system_flows

    def is_user_flow(self, flow_id: str) -> bool:
        return flow_id in self._user_flows

    def get_all_user_flow_ids(self) -> list[str]:
        return list(self._user_flows.keys())

    def get_all_system_flow_ids(self) -> list[str]:
        return list(self._system_flows.keys())

    def get_all_flow_ids(self) -> list[str]:
        return list(self._user_flows.keys()) + list(self._system_flows.keys())

    def get_slot_definitions(self) -> dict[str, dict]:
        return dict(self._user_slot_defs)

    def get_flow_name(self, flow_id: str) -> str:
        flow = self.get_flow(flow_id)
        if flow:
            return flow.get("name", flow_id)
        return flow_id

    def get_flow_description(self, flow_id: str) -> str:
        flow = self.get_flow(flow_id)
        if flow:
            return flow.get("description", "")
        return ""
