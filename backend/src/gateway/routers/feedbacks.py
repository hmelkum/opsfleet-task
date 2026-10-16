from fastapi import APIRouter, Body, Response, status
from fastapi.responses import JSONResponse

from src.core.fastapi.contexts.requests import RequestContextService
from src.core.fastapi.dependencies.wrappers import Inject, InjectScoped
from src.gateway.dtos.feedbacks import FeedbackErrorResponseDTO, PostFeedbackRequestDTO
from src.gateway.exceptions import ConversationNotFoundError, TurnNotFoundError
from src.gateway.services.feedbacks import FeedbackService

router = APIRouter(prefix="/feedbacks", tags=["Feedbacks"])


@router.post(
    "",
    summary="Rate a turn of a conversation",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Conversation or turn not found for this user."}},
)
async def post_feedback(
    dto: PostFeedbackRequestDTO = Body(...),
    ctx: RequestContextService = InjectScoped(),
    feedback_svc: FeedbackService = Inject()
) -> Response:
    try:
        await feedback_svc.rate(ctx.user, dto.conversation_id, dto.turn_id, dto.rating, dto.comment)
    except (ConversationNotFoundError, TurnNotFoundError):
        return JSONResponse(
            FeedbackErrorResponseDTO(detail="Conversation or turn not found.").dto_dump(),
            status_code=status.HTTP_404_NOT_FOUND
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
