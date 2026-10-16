from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.artifacts.entities.base import BaseArtifactsEntity


class ReportEntity(BaseArtifactsEntity):
    """A saved analysis report. Conversation-agnostic: the artifact envelope links it to a chat."""
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default_factory=uuid4,
        init=False
    )
    owner_id: Mapped[str] = mapped_column(
        String(length=255),
        nullable=False,
        index=True
    )
    title: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
    body: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        init=False
    )
