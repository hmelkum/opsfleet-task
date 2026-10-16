from uuid import UUID

from src.chat.models import MessageRole
from src.core.fastapi.dtos.base import BaseDTO


class ChatHistoryMessageDTO(BaseDTO):
    role: MessageRole
    content: str


class PostChatRequestDTO(BaseDTO):
    """Sent by the backend gateway. The agent is stateless: ``history`` carries the recent transcript."""
    conversation_id: UUID
    turn_id: UUID | None = None
    message: str
    history: list[ChatHistoryMessageDTO] = []
