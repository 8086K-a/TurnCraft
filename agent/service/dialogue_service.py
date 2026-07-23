from agent.domain.message import UserMessage, ProcessResult
from agent.repository.dialogue_state_repository import DialogueStateRepository
from agent.engine.dialogue_engine import DialogueEngine


class DialogueService:
    def __init__(
        self,
        dialogue_state_repository: DialogueStateRepository,
        dialogue_engine: DialogueEngine,
    ):
        self._repo = dialogue_state_repository
        self._engine = dialogue_engine

    async def process_message(self, user_message: UserMessage) -> ProcessResult:
        state = await self._repo.load(user_message.sender_id)
        result = await self._engine.process(state, user_message)
        await self._repo.save(state)
        return result
