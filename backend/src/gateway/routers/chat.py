from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from src.core.fastapi.contexts.requests import RequestContextService
from src.core.fastapi.dependencies.wrappers import Inject, InjectScoped
from src.gateway.dtos.chat import (
    ChatErrorResponseDTO,
    PostChatRequestDTO,
    PostChatResponseDTO,
    ToolCallDTO,
)
from src.gateway.exceptions import ConversationNotFoundError
from src.gateway.models.chat import ChatChunkModel, ChatChunkType
from src.gateway.services.chat import ChatService

router = APIRouter(prefix="/chat", tags=["Chat"])


def _not_found() -> JSONResponse:
    return JSONResponse(
        ChatErrorResponseDTO(detail="Conversation not found.").dto_dump(),
        status_code=status.HTTP_404_NOT_FOUND
    )


@router.post(
    "",
    summary="Send a message and get the full answer",
    response_model=PostChatResponseDTO,
    responses={404: {"description": "Conversation not found for this user."}},
)
async def chat(
    dto: PostChatRequestDTO = Body(...),
    ctx: RequestContextService = InjectScoped(),
    chat_svc: ChatService = Inject()
) -> Response:
    try:
        conversation_id = await chat_svc.open_conversation(ctx.user, dto.conversation_id)
    except ConversationNotFoundError:
        return _not_found()

    turn_id: UUID | None = None
    answer_parts: list[str] = []
    tool_calls: list[ToolCallDTO] = []
    confirmation: dict[str, Any] | None = None
    error: str | None = None
    async for chunk in chat_svc.stream(ctx.user, conversation_id, dto):
        match chunk.type:
            case ChatChunkType.CONVERSATION:
                turn_id = UUID(chunk.content["turnId"])
            case ChatChunkType.ANSWER:
                answer_parts.append(str(chunk.content))
            case ChatChunkType.TOOL_CALL:
                tool_calls.append(ToolCallDTO(**chunk.content))
            case ChatChunkType.CONFIRMATION_REQUIRED:
                confirmation = chunk.content
            case ChatChunkType.ERROR:
                error = str(chunk.content)

    return JSONResponse(
        PostChatResponseDTO(
            conversation_id=conversation_id,
            turn_id=turn_id,
            answer="".join(answer_parts),
            tool_calls=tool_calls,
            confirmation=confirmation,
            error=error
        ).dto_dump()
    )


@router.post(
    "/stream",
    summary="Send a message and stream the answer as NDJSON",
    description=(
        "Each line is a JSON object with `type` and `content`. The first line is "
        "always `conversation` with `{conversationId, turnId}`; then `answer`, `sql`, "
        "`confirmation_required` and `error` chunks."
    ),
    responses={404: {"description": "Conversation not found for this user."}},
)
async def chat_stream(
    dto: PostChatRequestDTO = Body(...),
    ctx: RequestContextService = InjectScoped(),
    chat_svc: ChatService = Inject()
) -> Response:
    try:
        conversation_id = await chat_svc.open_conversation(ctx.user, dto.conversation_id)
    except ConversationNotFoundError:
        return _not_found()

    return StreamingResponse(
        _ndjson(chat_svc.stream(ctx.user, conversation_id, dto)),
        media_type="application/x-ndjson"
    )


async def _ndjson(chunks: AsyncGenerator[ChatChunkModel, None]) -> AsyncGenerator[str, None]:
    async for chunk in chunks:
        yield chunk.model_dump_json() + "\n"
