import asyncio

from agent.domain.dialogue_state import DialogueState


class DialogueStateRepository:
    _states: dict[str, str] = {}
    _lock = asyncio.Lock()

    def __init__(self, db=None):
        self._db = db

    async def load(self, sender_id: str) -> DialogueState:
        async with self._lock:
            serialized = self._states.get(sender_id)
        if serialized is None:
            return DialogueState(sender_id=sender_id)
        return DialogueState.model_validate_json(serialized)

    async def save(self, state: DialogueState) -> None:
        async with self._lock:
            self._states[state.sender_id] = state.model_dump_json()

    @classmethod
    async def clear(cls) -> None:
        async with cls._lock:
            cls._states.clear()
