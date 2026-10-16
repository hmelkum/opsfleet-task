from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select, update

from src.artifacts.entities import (
    ArtifactEntity,
    DeletionAuditEntity,
    DeletionProposalEntity,
    ReportEntity,
)
from src.artifacts.enums import ArtifactKind, DeletionProposalStatus
from src.core.sqlalchemy.contexts.base import BaseDBContext


class DeletionRepository:
    def __init__(self, db_context: BaseDBContext) -> None:
        self._db_context = db_context

    async def add_proposal(self, proposal: DeletionProposalEntity) -> DeletionProposalEntity:
        """Stores the proposal; any older pending proposal in the conversation is cancelled."""
        async with self._db_context.session() as session:
            async with session.begin():
                await session.execute(
                    update(DeletionProposalEntity)
                    .where(DeletionProposalEntity.conversation_id == proposal.conversation_id)
                    .where(DeletionProposalEntity.status == DeletionProposalStatus.PENDING)
                    .values(status=DeletionProposalStatus.CANCELLED)
                )
                session.add(proposal)
            await session.refresh(proposal)
            return proposal

    async def get_proposal(self, proposal_id: UUID) -> DeletionProposalEntity | None:
        async with self._db_context.session() as session:
            return await session.get(DeletionProposalEntity, proposal_id)

    async def close_proposal(self, proposal_id: UUID, status: DeletionProposalStatus) -> bool:
        """Moves a pending proposal to ``status``. False if it was no longer pending."""
        async with self._db_context.session() as session:
            async with session.begin():
                result = await session.execute(
                    update(DeletionProposalEntity)
                    .where(DeletionProposalEntity.id == proposal_id)
                    .where(DeletionProposalEntity.status == DeletionProposalStatus.PENDING)
                    .values(status=status)
                )
            return result.rowcount > 0

    async def execute(
        self,
        proposal_id: UUID,
        actor_id: str,
        owner_id: str | None
    ) -> Sequence[tuple[UUID, str, str]] | None:
        """Deletes exactly the proposal's reports, audits them and marks the proposal executed.

        One transaction; the proposal row is locked so a proposal executes at most once.
        ``owner_id=None`` lets the actor delete any owner's reports (admin).
        Returns ``(id, title, owner_id)`` per deleted report, or None if the proposal is no longer pending.
        """
        async with self._db_context.session() as session:
            async with session.begin():
                proposal = (
                    await session.execute(
                        select(DeletionProposalEntity)
                        .where(DeletionProposalEntity.id == proposal_id)
                        .where(DeletionProposalEntity.status == DeletionProposalStatus.PENDING)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if proposal is None:
                    return None

                report_filter = ReportEntity.id.in_(proposal.report_ids)
                if owner_id is not None:
                    report_filter = report_filter & (ReportEntity.owner_id == owner_id)

                deleted = (
                    await session.execute(
                        delete(ReportEntity)
                        .where(report_filter)
                        .returning(ReportEntity.id, ReportEntity.title, ReportEntity.owner_id)
                    )
                ).all()

                deleted_ids = [row.id for row in deleted]
                if deleted_ids:
                    await session.execute(
                        delete(ArtifactEntity)
                        .where(ArtifactEntity.kind == ArtifactKind.REPORT)
                        .where(ArtifactEntity.ref_id.in_(deleted_ids))
                    )
                    session.add_all(
                        DeletionAuditEntity(
                            proposal_id=proposal_id,
                            actor_id=actor_id,
                            report_id=row.id,
                            report_title=row.title,
                            report_owner_id=row.owner_id
                        )
                        for row in deleted
                    )

                proposal.status = DeletionProposalStatus.EXECUTED

            return [(row.id, row.title, row.owner_id) for row in deleted]
