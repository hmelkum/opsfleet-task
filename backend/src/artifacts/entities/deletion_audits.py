from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.artifacts.entities.base import BaseArtifactsEntity


class DeletionAuditEntity(BaseArtifactsEntity):
    """One row per deleted report. Keeps ids and titles, never report bodies."""
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default_factory=uuid4,
        init=False
    )
    proposal_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True
    )
    actor_id: Mapped[str] = mapped_column(
        String(length=255),
        nullable=False
    )
    report_id: Mapped[UUID] = mapped_column(
        nullable=False
    )
    report_title: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
    report_owner_id: Mapped[str] = mapped_column(
        String(length=255),
        nullable=False
    )
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        init=False
    )
