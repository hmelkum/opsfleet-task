from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import or_, select

from src.artifacts.entities import ArtifactEntity, ReportEntity
from src.artifacts.enums import ArtifactKind
from src.core.sqlalchemy.contexts.base import BaseDBContext


class ReportRepository:
    def __init__(self, db_context: BaseDBContext) -> None:
        self._db_context = db_context

    async def add(self, report: ReportEntity, conversation_id: UUID) -> ReportEntity:
        """Stores the report and its artifact envelope in one transaction."""
        async with self._db_context.session() as session:
            async with session.begin():
                session.add(report)
                session.add(
                    ArtifactEntity(
                        kind=ArtifactKind.REPORT,
                        ref_id=report.id,
                        owner_id=report.owner_id,
                        conversation_id=conversation_id,
                        title=report.title
                    )
                )
            await session.refresh(report)
            return report

    async def get(self, report_id: UUID, owner_id: str | None) -> ReportEntity | None:
        stmt = select(ReportEntity).where(ReportEntity.id == report_id)
        if owner_id is not None:
            stmt = stmt.where(ReportEntity.owner_id == owner_id)
        async with self._db_context.session() as session:
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_by_ids(self, report_ids: Sequence[UUID], owner_id: str | None) -> Sequence[ReportEntity]:
        stmt = (
            select(ReportEntity)
            .where(ReportEntity.id.in_(report_ids))
            .order_by(ReportEntity.created_at.desc())
        )
        if owner_id is not None:
            stmt = stmt.where(ReportEntity.owner_id == owner_id)
        async with self._db_context.session() as session:
            result = await session.execute(stmt)
            return result.scalars().all()

    async def search(
        self,
        owner_id: str | None,
        text: str | None,
        conversation_id: UUID | None,
        limit: int
    ) -> Sequence[ReportEntity]:
        """``owner_id=None`` searches every owner's reports (admin)."""
        stmt = select(ReportEntity)
        if owner_id is not None:
            stmt = stmt.where(ReportEntity.owner_id == owner_id)
        if conversation_id is not None:
            stmt = stmt.join(
                ArtifactEntity,
                (ArtifactEntity.kind == ArtifactKind.REPORT) & (ArtifactEntity.ref_id == ReportEntity.id)
            ).where(ArtifactEntity.conversation_id == conversation_id)
        if text:
            pattern = f"%{self._escape_like(text)}%"
            stmt = stmt.where(
                or_(
                    ReportEntity.title.ilike(pattern, escape="\\"),
                    ReportEntity.body.ilike(pattern, escape="\\")
                )
            )
        stmt = stmt.order_by(ReportEntity.created_at.desc()).limit(limit)
        async with self._db_context.session() as session:
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    def _escape_like(text: str) -> str:
        return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
