import uuid

from fastapi import APIRouter
from fastapi.params import Depends

from agent.api.dependencies import get_dialogue_service, get_repository
from agent.api.schemas import ChatRequest, ChatResponse, HistoryResponse, ChatBotMessage, HistoryMessage, ChatObject
from agent.domain.message import UserMessage, ProcessResult, MessageType, MessageObject
from agent.service.dialogue_service import DialogueService
from agent.repository.dialogue_state_repository import DialogueStateRepository

chat_router = APIRouter()


@chat_router.post('/api/chat')
async def chat(
        chat_request: ChatRequest,
        dialogue_service: DialogueService = Depends(get_dialogue_service)
) -> ChatResponse:
    process_result: ProcessResult = await dialogue_service.process_message(_build_user_message(chat_request))
    return _build_chat_response(process_result)


@chat_router.get('/api/chat/history')
async def history(
        sender_id: str,
        repository: DialogueStateRepository = Depends(get_repository),
) -> HistoryResponse:
    state = await repository.load(sender_id)
    messages: list[HistoryMessage] = []
    for session in state.sessions:
        for turn in session.turns:
            messages.append(_history_user_message(turn.input_message))
            messages.extend(
                _history_bot_message(message) for message in turn.assistant_messages
            )
    return HistoryResponse(
        sender_id=sender_id,
        messages=messages,
    )


def _history_user_message(message: UserMessage) -> HistoryMessage:
    return HistoryMessage(
        role="user",
        text=message.text,
        object=_build_history_object(message.object),
    )


def _history_bot_message(message) -> HistoryMessage:
    return HistoryMessage(
        role="bot",
        text=message.text,
        object=_build_history_object(message.object),
    )


def _build_history_object(message_object: MessageObject | None) -> ChatObject | None:
    if message_object is None:
        return None
    return ChatObject(
        type=message_object.type,
        id=message_object.id,
        title=message_object.title,
        attributes=message_object.attributes,
    )


def _build_user_message(chat_request: ChatRequest) -> UserMessage:
    return UserMessage(
        sender_id=chat_request.sender_id,
        message_id=chat_request.message_id or str(uuid.uuid4()),
        type=MessageType.TEXT if chat_request.text else MessageType.OBJECT,
        text=chat_request.text,
        object=MessageObject(type=chat_request.object.type,
                             id=chat_request.object.id,
                             title=chat_request.object.title,
                             attributes=chat_request.object.attributes
                             ) if chat_request.object else None
    )


def _build_chat_response(process_result: ProcessResult) -> ChatResponse:
    return ChatResponse(
        sender_id=process_result.sender_id,
        message_id=process_result.message_id,
        messages=[ChatBotMessage(
            text=message.text,
            object=ChatObject(type=message.object.type,
                              id=message.object.id,
                              title=message.object.title,
                              attributes=message.object.attributes
                              ) if message.object else None
        ) for message in process_result.messages],
        trace=process_result.trace,
    )
