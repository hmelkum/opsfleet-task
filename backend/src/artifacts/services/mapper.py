from collections.abc import Sequence

from src.artifacts.entities import DeletionProposalEntity, ReportEntity
from src.artifacts.enums import DeletionProposalStatus
from src.artifacts.models.deletions import DeletionProposalModel
from src.artifacts.models.reports import ReportModel


def map_report_entity_to_model(entity: ReportEntity) -> ReportModel:
    return ReportModel(
        id=entity.id,
        owner_id=entity.owner_id,
        title=entity.title,
        body=entity.body,
        created_at=entity.created_at
    )


def map_report_entity_seq_to_model_list(entities: Sequence[ReportEntity]) -> list[ReportModel]:
    return [map_report_entity_to_model(entity) for entity in entities]


def map_proposal_entity_to_model(entity: DeletionProposalEntity) -> DeletionProposalModel:
    return DeletionProposalModel(
        id=entity.id,
        user_id=entity.user_id,
        conversation_id=entity.conversation_id,
        report_ids=entity.report_ids,
        status=DeletionProposalStatus(entity.status),
        expires_at=entity.expires_at
    )
