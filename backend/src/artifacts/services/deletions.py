"""
Two-step report deletion.

``propose`` resolves which reports would go, stores a short-lived, single-use
proposal bound to the user and conversation, and deletes nothing. It is the
only step the model can reach (as a tool). ``execute`` and ``cancel`` implement
the core ``DeletionPort``: the chat gateway calls them after the user answered
a structured confirmation in the CLI, never because the model read a "yes".
"""
from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.artifacts.config import BaseArtifactsConfigService
from src.artifacts.entities import DeletionProposalEntity
from src.artifacts.enums import DeletionProposalStatus
from src.artifacts.models.deletions import (
    DeletionPreviewModel,
    DeletionProposalModel,
)
from src.artifacts.repositories.deletions import DeletionRepository
from src.artifacts.services.mapper import map_proposal_entity_to_model
from src.artifacts.services.reports import ReportService
from src.core.deletions.port import (
    DeletedReport,
    DeletionPort,
    DeletionProposalNotFoundError,
    DeletionProposalNotPendingError,
)
from src.core.fastapi.dependencies.wrappers import InjectPlaceholder
from src.core.identity.users import UserContext
from src.core.observability.events import emit


class DeletionService(DeletionPort):
    def __init__(
        self,
        report_svc: ReportService = InjectPlaceholder(),
        deletion_repo: DeletionRepository = InjectPlaceholder(),
        artifacts_config_service: BaseArtifactsConfigService = InjectPlaceholder()
    ) -> None:
        self._report_svc = report_svc
        self._deletion_repo = deletion_repo
        self._config = artifacts_config_service.artifacts

    async def propose(
        self,
        user: UserContext,
        conversation_id: UUID,
        text: str | None,
        in_conversation: bool,
        report_ids: list[UUID] | None
    ) -> DeletionPreviewModel | None:
        """Returns the preview, or None when nothing matches (no proposal is stored)."""
        if report_ids:
            reports = await self._report_svc.get_many(user, report_ids)
        else:
            reports = await self._report_svc.search(
                user,
                text=text,
                conversation_id=conversation_id if in_conversation else None
            )
        if not reports:
            emit("deletion_proposed", proposal_id=None, reports=0)
            return None

        proposal = await self._deletion_repo.add_proposal(
            DeletionProposalEntity(
                user_id=user.user_id,
                conversation_id=conversation_id,
                report_ids=[report.id for report in reports],
                status=DeletionProposalStatus.PENDING,
                expires_at=datetime.now(UTC) + timedelta(seconds=self._config.deletion_proposal_ttl_s)
            )
        )
        emit("deletion_proposed", proposal_id=str(proposal.id), reports=len(reports))
        return DeletionPreviewModel(
            proposal_id=proposal.id,
            expires_at=proposal.expires_at,
            reports=reports
        )

    async def execute(self, user: UserContext, conversation_id: UUID, proposal_id: UUID) -> list[DeletedReport]:
        await self._get_pending(user, conversation_id, proposal_id)

        deleted = await self._deletion_repo.execute(
            proposal_id,
            actor_id=user.user_id,
            owner_id=None if user.is_admin else user.user_id
        )
        if deleted is None:  # executed or cancelled concurrently
            emit("deletion_rejected", proposal_id=str(proposal_id), reason=DeletionProposalStatus.EXECUTED.value)
            raise DeletionProposalNotPendingError(DeletionProposalStatus.EXECUTED.value)

        emit("deletion_executed", proposal_id=str(proposal_id), reports=len(deleted))

        return [
            DeletedReport(id=report_id, title=title, owner_id=owner_id)
            for report_id, title, owner_id in deleted
        ]

    async def cancel(self, user: UserContext, conversation_id: UUID, proposal_id: UUID) -> None:
        await self._get_pending(user, conversation_id, proposal_id)
        if not await self._deletion_repo.close_proposal(proposal_id, DeletionProposalStatus.CANCELLED):
            raise DeletionProposalNotPendingError(DeletionProposalStatus.CANCELLED.value)
        emit("deletion_cancelled", proposal_id=str(proposal_id))

    async def _get_pending(self, user: UserContext, conversation_id: UUID, proposal_id: UUID) -> DeletionProposalModel:
        """The proposal if it belongs to this user and conversation and can still be acted on."""
        entity = await self._deletion_repo.get_proposal(proposal_id)
        if (
            entity is None
            or entity.user_id != user.user_id
            or entity.conversation_id != conversation_id
        ):
            emit("deletion_rejected", proposal_id=str(proposal_id), reason="not_found")
            raise DeletionProposalNotFoundError()

        proposal = map_proposal_entity_to_model(entity)
        if proposal.status != DeletionProposalStatus.PENDING:
            emit("deletion_rejected", proposal_id=str(proposal_id), reason=proposal.status.value)
            raise DeletionProposalNotPendingError(proposal.status.value)

        if proposal.expires_at <= datetime.now(UTC):
            await self._deletion_repo.close_proposal(proposal_id, DeletionProposalStatus.EXPIRED)
            emit("deletion_rejected", proposal_id=str(proposal_id), reason=DeletionProposalStatus.EXPIRED.value)
            raise DeletionProposalNotPendingError(DeletionProposalStatus.EXPIRED.value)

        return proposal
