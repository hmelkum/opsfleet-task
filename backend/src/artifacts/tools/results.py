from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from src.core.fastmcp.tools.results import SuccessToolResult


class ReportSummaryResult(BaseModel):
    id: UUID
    title: str
    owner_id: str
    created_at: datetime


class SaveReportToolResult(SuccessToolResult):
    report: ReportSummaryResult


class SearchReportsToolResult(SuccessToolResult):
    reports: list[ReportSummaryResult]


class GetReportToolResult(SuccessToolResult):
    report: ReportSummaryResult
    body: str


class ProposeReportsDeletionToolResult(SuccessToolResult):
    proposal_id: UUID | None
    expires_at: datetime | None
    reports: list[ReportSummaryResult]
