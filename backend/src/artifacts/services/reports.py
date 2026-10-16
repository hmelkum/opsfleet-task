from uuid import UUID

from src.artifacts.config import BaseArtifactsConfigService
from src.artifacts.entities import ReportEntity
from src.artifacts.models.reports import ReportModel
from src.artifacts.repositories.reports import ReportRepository
from src.artifacts.services.mapper import (
    map_report_entity_seq_to_model_list,
    map_report_entity_to_model,
)
from src.core.identity.users import UserContext
from src.core.observability.events import emit
from src.core.pii.masking import mask_pii


class ReportService:
    """Users see their own reports; admin sees everyone's."""

    def __init__(
        self,
        report_repo: ReportRepository,
        artifacts_config_service: BaseArtifactsConfigService
    ) -> None:
        self._report_repo = report_repo
        self._config = artifacts_config_service.artifacts

    async def save(self, user: UserContext, conversation_id: UUID, title: str, body: str) -> ReportModel:
        """Reports are masked before they are stored; saved text outlives the conversation."""
        title, title_counts = mask_pii(title)
        body, body_counts = mask_pii(body)
        entity = await self._report_repo.add(
            ReportEntity(
                owner_id=user.user_id,
                title=title,
                body=body
            ),
            conversation_id
        )
        emit("report_saved", report_id=str(entity.id), body_chars=len(body), pii_masked=dict(title_counts + body_counts))
        return map_report_entity_to_model(entity)

    async def get(self, user: UserContext, report_id: UUID) -> ReportModel | None:
        entity = await self._report_repo.get(report_id, self._owner_filter(user))
        if entity:
            return map_report_entity_to_model(entity)
        return None

    async def get_many(self, user: UserContext, report_ids: list[UUID]) -> list[ReportModel]:
        entities = await self._report_repo.get_by_ids(report_ids, self._owner_filter(user))
        return map_report_entity_seq_to_model_list(entities)

    async def search(
        self,
        user: UserContext,
        text: str | None,
        conversation_id: UUID | None
    ) -> list[ReportModel]:
        entities = await self._report_repo.search(
            owner_id=self._owner_filter(user),
            text=text,
            conversation_id=conversation_id,
            limit=self._config.max_search_results
        )
        return map_report_entity_seq_to_model_list(entities)

    @staticmethod
    def _owner_filter(user: UserContext) -> str | None:
        return None if user.is_admin else user.user_id
