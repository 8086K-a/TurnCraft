import logging
from typing import Any

from jinja2 import Template

from agent.domain.dialogue_state import DialogueState
from agent.domain.message import MessageType, UserMessage
from agent.prompts.history_builder import HistoryBuilder
from agent.prompts.prompt_loader import load_prompt


logger = logging.getLogger(__name__)


class ChitchatHandler:
    def __init__(self, llm):
        self._llm = llm
        self._template = Template(load_prompt("chitchat_respond"))

    async def handle(
        self, state: DialogueState, user_message: UserMessage
    ) -> str:
        prompt = self._template.render(
            history=self._history(state),
            user_message=self._render_user_message(user_message),
        )
        try:
            response = await self._llm.ainvoke(prompt)
            text = self._response_text(response.content).strip()
            if text:
                return text
        except Exception:
            logger.exception("Failed to generate chitchat response")
        return "我在听，你可以继续说。"

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
    def _response_text(content: Any) -> str:
        if isinstance(content, list):
            return "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        return str(content)


async def handle_chitchat(user_message: str) -> str:
    """Compatibility fallback for callers that do not provide an LLM."""
    return "我在听，你可以继续说。"
