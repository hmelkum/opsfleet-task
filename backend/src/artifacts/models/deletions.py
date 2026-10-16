from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from src.artifacts.enums import DeletionProposalStatus
from src.artifacts.models.reports import ReportModel


class DeletionProposalModel(BaseModel):
    id: UUID
    user_id: str
    conversation_id: UUID
    report_ids: list[UUID]
    status: DeletionProposalStatus
    expires_at: datetime


class DeletionPreviewModel(BaseModel):
    proposal_id: UUID
    expires_at: datetime
    reports: list[ReportModel]

