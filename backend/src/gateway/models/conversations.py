from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from src.gateway.models.chat import MessageRole


class ConversationSummaryModel(BaseModel):
    id: UUID
    title: str
    message_count: int
    created_at: datetime
    last_message_at: datetime


class MessageModel(BaseModel):
    role: MessageRole
    content: str
    created_at: datetime
