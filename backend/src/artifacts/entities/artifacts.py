from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.artifacts.entities.base import BaseArtifactsEntity


class ArtifactEntity(BaseArtifactsEntity):
    """Envelope linking an artifact of any kind (``ref_id`` points into the kind's own table) to a conversation."""
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default_factory=uuid4,
        init=False
    )
    kind: Mapped[str] = mapped_column(
        String(length=32),
        nullable=False
    )
    ref_id: Mapped[UUID] = mapped_column(
        nullable=False
    )
    owner_id: Mapped[str] = mapped_column(
        String(length=255),
        nullable=False,
        index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True
    )
    title: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        init=False
    )

    __table_args__ = (
        UniqueConstraint("kind", "ref_id"),
    )
