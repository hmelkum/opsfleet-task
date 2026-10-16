from typing import Annotated
from uuid import UUID

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from pydantic import Field

from src.artifacts.models.reports import ReportModel
from src.artifacts.services.deletions import DeletionService
from src.artifacts.services.reports import ReportService
from src.artifacts.tools.results import (
    GetReportToolResult,
    ProposeReportsDeletionToolResult,
    ReportSummaryResult,
    SaveReportToolResult,
    SearchReportsToolResult,
)
from src.core.fastmcp.tools.dependencies import get_conversation_id, get_user_context
from src.core.fastmcp.tools.results import ErrorToolResult, RetryGuidance
from src.core.identity.users import UserContext


class ArtifactToolset:
    def __init__(
        self,
        report_svc: ReportService,
        deletion_svc: DeletionService
    ) -> None:
        self._report_svc = report_svc
        self._deletion_svc = deletion_svc

    @tool
    async def save_report(
        self,
        title: Annotated[str, Field(
            min_length=1,
            max_length=200,
            description="Short, descriptive report title, e.g. 'Q1 2026 revenue by category'."
        )],
        body: Annotated[str, Field(
            min_length=1,
            max_length=50000,
            description=(
                "The full report in Markdown: summary, findings, caveats, and "
                "action items. Aggregates only; never customer-level personal data."
            )
        )],
        user: UserContext = Depends(get_user_context),
        conversation_id: UUID = Depends(get_conversation_id)
    ) -> SaveReportToolResult | ErrorToolResult:
        """
        Saves a report to the user's report library and links it to the
        current conversation.

        Call it only when the user asks to create or save a report, after the
        analysis is done and the report text is final.
        """
        report = await self._report_svc.save(user, conversation_id, title, body)
        return SaveReportToolResult(report=self._summary(report))

    @tool
    async def search_reports(
        self,
        text: Annotated[str | None, Field(
            default=None,
            description=(
                "Case-insensitive text matched against report titles and bodies, "
                "e.g. a brand, category, or topic. Omit to list all reports."
            )
        )] = None,
        in_conversation: Annotated[bool, Field(
            default=False,
            description="True to only include reports created in the current conversation."
        )] = False,
        user: UserContext = Depends(get_user_context),
        conversation_id: UUID = Depends(get_conversation_id)
    ) -> SearchReportsToolResult | ErrorToolResult:
        """
        Lists saved reports visible to the user, newest first. Users see their
        own reports; the administrator sees everyone's.

        Returns titles and ids, not report bodies; use ``get_report`` to read one.
        """
        reports = await self._report_svc.search(
            user,
            text=text,
            conversation_id=conversation_id if in_conversation else None
        )
        return SearchReportsToolResult(reports=[self._summary(report) for report in reports])

    @tool
    async def get_report(
        self,
        report_id: Annotated[UUID, Field(
            description="Identifier of the report, as returned by `search_reports` or `save_report`."
        )],
        user: UserContext = Depends(get_user_context)
    ) -> GetReportToolResult | ErrorToolResult:
        """
        Returns one saved report with its full Markdown body.
        """
        report = await self._report_svc.get(user, report_id)
        if report is None:
            return ErrorToolResult(
                error="Report not found.",
                retry=RetryGuidance.DO_NOT_RETRY
            )
        return GetReportToolResult(report=self._summary(report), body=report.body)

    @tool
    async def propose_reports_deletion(
        self,
        text: Annotated[str | None, Field(
            default=None,
            description=(
                "Delete reports whose title or body mention this text "
                "(case-insensitive), e.g. 'Calvin Klein'."
            )
        )] = None,
        in_conversation: Annotated[bool, Field(
            default=False,
            description="True to only include reports created in the current conversation."
        )] = False,
        report_ids: Annotated[list[UUID] | None, Field(
            default=None,
            description=(
                "Exact report ids, as returned by `search_reports`. When given, "
                "`text` and `in_conversation` are ignored."
            )
        )] = None,
        user: UserContext = Depends(get_user_context),
        conversation_id: UUID = Depends(get_conversation_id)
    ) -> ProposeReportsDeletionToolResult | ErrorToolResult:
        """
        Prepares a deletion of saved reports. NOTHING IS DELETED by this tool.

        It resolves which reports match and returns them with a
        ``proposal_id``. The user then confirms or declines in their client;
        only that confirmation deletes. Never tell the user reports were
        deleted based on this result. With no filters, every report the user
        can see matches.

        When nothing matches, ``proposal_id`` is null and ``reports`` is empty:
        tell the user there is nothing to delete.
        """
        preview = await self._deletion_svc.propose(
            user,
            conversation_id,
            text=text,
            in_conversation=in_conversation,
            report_ids=report_ids
        )
        if preview is None:
            return ProposeReportsDeletionToolResult(proposal_id=None, expires_at=None, reports=[])

        return ProposeReportsDeletionToolResult(
            proposal_id=preview.proposal_id,
            expires_at=preview.expires_at,
            reports=[self._summary(report) for report in preview.reports]
        )

    @staticmethod
    def _summary(report: ReportModel) -> ReportSummaryResult:
        return ReportSummaryResult(
            id=report.id,
            title=report.title,
            owner_id=report.owner_id,
            created_at=report.created_at
        )
