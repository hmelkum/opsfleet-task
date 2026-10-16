from datetime import datetime
from uuid import UUID

from src.core.fastapi.dtos.base import BaseDTO
from src.gateway.models.chat import MessageRole


class ConversationSummaryDTO(BaseDTO):
    id: UUID
    title: str
    message_count: int
    created_at: datetime
    last_message_at: datetime


class GetConversationsResponseDTO(BaseDTO):
    conversations: list[ConversationSummaryDTO]


class MessageDTO(BaseDTO):
    role: MessageRole
    content: str
    created_at: datetime


class GetConversationMessagesResponseDTO(BaseDTO):
    messages: list[MessageDTO]


class ConversationErrorResponseDTO(BaseDTO):
    detail: str
