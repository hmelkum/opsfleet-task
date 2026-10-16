from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from src.artifacts.entities.base import BaseArtifactsEntity


class DeletionProposalEntity(BaseArtifactsEntity):
    """A previewed delete waiting for the user's structured confirmation. Single use, short-lived."""
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default_factory=uuid4,
        init=False
    )
    user_id: Mapped[str] = mapped_column(
        String(length=255),
        nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True
    )
    report_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid),
        nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(length=32),
        nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        init=False
    )
