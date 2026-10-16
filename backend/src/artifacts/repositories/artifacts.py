from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from src.artifacts.entities import ArtifactEntity
from src.core.sqlalchemy.contexts.base import BaseDBContext


class ArtifactRepository:
    """The artifact envelope: one row per artifact of any kind, linking it to its owner and conversation."""

    def __init__(self, db_context: BaseDBContext) -> None:
        self._db_context = db_context

    async def list(self, owner_id: str | None, limit: int) -> Sequence[ArtifactEntity]:
        """``owner_id=None`` lists every owner's artifacts (admin)."""
        stmt = select(ArtifactEntity).order_by(ArtifactEntity.created_at.desc()).limit(limit)
        if owner_id is not None:
            stmt = stmt.where(ArtifactEntity.owner_id == owner_id)
        async with self._db_context.session() as session:
            result = await session.execute(stmt)
            return result.scalars().all()

    async def get(self, artifact_id: UUID, owner_id: str | None) -> ArtifactEntity | None:
        stmt = select(ArtifactEntity).where(ArtifactEntity.id == artifact_id)
        if owner_id is not None:
            stmt = stmt.where(ArtifactEntity.owner_id == owner_id)
        async with self._db_context.session() as session:
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
