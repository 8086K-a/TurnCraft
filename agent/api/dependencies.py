from fastapi import Depends

from agent.engine.builder import build_dialogue_engine
from agent.engine.dialogue_engine import DialogueEngine
from agent.infrastructure.database import db
from agent.repository.dialogue_state_repository import DialogueStateRepository
from agent.service.dialogue_service import DialogueService

_dialogue_engine: DialogueEngine | None = None


def init_dialogue_engine() -> None:
    global _dialogue_engine
    _dialogue_engine = build_dialogue_engine()


def get_engine() -> DialogueEngine:
    return _dialogue_engine


async def get_db():
    async with db.session() as session:
        yield session


async def get_repository() -> DialogueStateRepository:
    return DialogueStateRepository()


async def get_dialogue_service(
        engine: DialogueEngine = Depends(get_engine),
        repository: DialogueStateRepository = Depends(get_repository),
) -> DialogueService:
    return DialogueService(dialogue_state_repository=repository, dialogue_engine=engine)
