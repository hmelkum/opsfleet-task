from collections.abc import AsyncGenerator

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse

from src.chat.dtos import PostChatRequestDTO
from src.chat.models import ChatChunkModel
from src.chat.service import ChatService
from src.core.fastapi.contexts.requests import RequestContextService
from src.core.fastapi.dependencies.wrappers import Inject, InjectScoped

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post(
    "/stream",
    summary="Run one agent turn and stream it as NDJSON",
    description=(
        "Called by the backend gateway. Each line is a JSON object with `type` "
        "(answer, tool_call, confirmation_required, error, title) and `content`."
    ),
)
async def chat_stream(
    dto: PostChatRequestDTO = Body(...),
    ctx: RequestContextService = InjectScoped(),
    chat_svc: ChatService = Inject()
) -> StreamingResponse:
    return StreamingResponse(
        _ndjson(chat_svc.stream(ctx.user.user_id, dto)),
        media_type="application/x-ndjson"
    )


async def _ndjson(chunks: AsyncGenerator[ChatChunkModel, None]) -> AsyncGenerator[str, None]:
    async for chunk in chunks:
        yield chunk.model_dump_json() + "\n"
