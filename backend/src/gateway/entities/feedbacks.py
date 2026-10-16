from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.gateway.entities.base import BaseChatEntity
from src.gateway.entities.conversations import ConversationEntity
from src.gateway.entities.messages import MessageEntity


class FeedbackEntity(BaseChatEntity):
    """A user's rating of one turn (identified by the user's message). Rating again replaces it."""
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default_factory=uuid4,
        init=False
    )
    turn_id: Mapped[UUID] = mapped_column(
        ForeignKey(MessageEntity.id, ondelete="CASCADE"),
        nullable=False,
        unique=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey(ConversationEntity.id, ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(length=255),
        nullable=False
    )
    rating: Mapped[str] = mapped_column(
        String(length=8),
        nullable=False
    )
    comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        init=False
    )
