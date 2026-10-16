from uuid import UUID

from fastapi import APIRouter, Path, Response, status
from fastapi.responses import JSONResponse

from src.core.fastapi.contexts.requests import RequestContextService
from src.core.fastapi.dependencies.wrappers import Inject, InjectScoped
from src.gateway.dtos.conversations import (
    ConversationErrorResponseDTO,
    ConversationSummaryDTO,
    GetConversationMessagesResponseDTO,
    GetConversationsResponseDTO,
    MessageDTO,
)
from src.gateway.exceptions import ConversationNotFoundError
from src.gateway.services.conversations import ConversationService

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get(
    "",
    summary="List the caller's conversations, most recently active first",
    response_model=GetConversationsResponseDTO,
)
async def get_conversations(
    ctx: RequestContextService = InjectScoped(),
    conversation_svc: ConversationService = Inject()
) -> Response:
    conversations = await conversation_svc.get_summaries(ctx.user)
    return JSONResponse(
        GetConversationsResponseDTO(
            conversations=[ConversationSummaryDTO(**c.model_dump()) for c in conversations]
        ).dto_dump()
    )


@router.get(
    "/{conversation_id}/messages",
    summary="The transcript of one of the caller's conversations, oldest first",
    response_model=GetConversationMessagesResponseDTO,
    responses={404: {"description": "Conversation not found for this user."}},
)
async def get_conversation_messages(
    conversation_id: UUID = Path(...),
    ctx: RequestContextService = InjectScoped(),
    conversation_svc: ConversationService = Inject()
) -> Response:
    try:
        messages = await conversation_svc.get_messages(ctx.user, conversation_id)
    except ConversationNotFoundError:
        return JSONResponse(
            ConversationErrorResponseDTO(detail="Conversation not found.").dto_dump(),
            status_code=status.HTTP_404_NOT_FOUND
        )
    return JSONResponse(
        GetConversationMessagesResponseDTO(messages=[MessageDTO(**m.model_dump()) for m in messages]).dto_dump()
    )
