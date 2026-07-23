import json
import re
from typing import Any

from jinja2 import Template
from pydantic import BaseModel, Field

from agent.domain.dialogue_state import DialogueState
from agent.domain.message import MessageType, UserMessage
from agent.handler.task.flow import FlowManager
from agent.handler.knowledge import KNOWLEDGE_INTENTS
from agent.prompts.history_builder import HistoryBuilder
from agent.prompts.prompt_loader import load_prompt


class TaskPlan(BaseModel):
    commands: list[dict[str, Any]] = Field(default_factory=list)


class TurnPlan(BaseModel):
    task: TaskPlan | None = None
    knowledge: dict[str, Any] | None = None
    chitchat: dict[str, Any] | None = None


class TurnPlanner:
    def __init__(self, llm, flow_manager: FlowManager):
        self._llm = llm
        self._flow_manager = flow_manager
        self._template = Template(load_prompt("turn_plan"))

    async def plan(self, state: DialogueState, user_message: UserMessage) -> TurnPlan:
        prompt = self._template.render(
            available_flows_json=json.dumps(
                self._available_flows(), ensure_ascii=False
            ),
            knowledge_intents_json=json.dumps(KNOWLEDGE_INTENTS, ensure_ascii=False),
            active_task_json=self._dump(state.active_task),
            interrupted_tasks_json=self._dump(state.paused_tasks),
            focused_object_json=self._dump(state.focused_object),
            current_conversation=self._history(state),
            user_message=self._render_user_message(user_message),
        )
        response = await self._llm.ainvoke(prompt)
        return TurnPlan.model_validate_json(self._extract_json(response.content))

    def _available_flows(self) -> list[dict[str, str]]:
        return [
            {
                "id": flow_id,
                "name": self._flow_manager.get_flow_name(flow_id),
                "description": self._flow_manager.get_flow_description(flow_id),
            }
            for flow_id in self._flow_manager.get_all_user_flow_ids()
        ]

    @staticmethod
    def _dump(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, list):
            data = [item.model_dump(mode="json") for item in value]
        else:
            data = value.model_dump(mode="json")
        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def _history(state: DialogueState) -> str:
        if not state.current_session_id:
            return ""
        session = next(
            (
                item
                for item in state.sessions
                if item.session_id == state.current_session_id
            ),
            None,
        )
        return HistoryBuilder.build(session.turns) if session else ""

    @staticmethod
    def _render_user_message(user_message: UserMessage) -> str:
        if user_message.type == MessageType.TEXT:
            return user_message.text or ""
        if user_message.object is None:
            return ""
        return HistoryBuilder._render_object(user_message.object)

    @staticmethod
    def _extract_json(content: Any) -> str:
        if isinstance(content, list):
            content = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        text = str(content).strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("LLM did not return a JSON object")
        return text[start : end + 1]
