from agent.engine.turn_planner import TurnPlan


class TurnPlanValidator:
    """Validate the planner contract before any command is executed."""

    def __init__(self, flow_manager):
        self._flow_manager = flow_manager

    def validate(self, plan: TurnPlan) -> TurnPlan:
        if plan.task is not None:
            for command in plan.task.commands:
                name = command.get("command")
                if name not in {"start_flow", "resume_flow", "cancel_flow", "set_slots"}:
                    raise ValueError(f"unsupported task command: {name}")
                flow_id = command.get("flow")
                if name in {"start_flow", "resume_flow"} and not self._flow_manager.get_flow(flow_id):
                    raise ValueError(f"unknown flow: {flow_id}")
        if plan.knowledge is not None:
            intents = plan.knowledge.get("intents")
            if not isinstance(intents, list) or not all(isinstance(item, str) for item in intents):
                raise ValueError("knowledge.intents must be a list of strings")
        return plan
