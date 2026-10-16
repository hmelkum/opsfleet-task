"""DeletionService rules with in-memory repositories. Database behaviour is covered by the integration run."""
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.artifacts.config import ArtifactsConfigModel
from src.artifacts.entities import ReportEntity
from src.artifacts.enums import DeletionProposalStatus
from src.artifacts.services.deletions import DeletionService
from src.artifacts.services.reports import ReportService
from src.core.deletions.port import (
    DeletionProposalNotFoundError,
    DeletionProposalNotPendingError,
)
from src.core.identity.users import parse_user_id

ADMIN = parse_user_id("admin")
ALICE = parse_user_id("user_alice")
BOB = parse_user_id("user_bob")
CONVERSATION = uuid4()


def report(owner_id: str, title: str) -> ReportEntity:
    entity = ReportEntity(owner_id=owner_id, title=title, body=f"{title} body")
    entity.created_at = datetime.now(UTC)
    return entity


class FakeReportRepository:
    def __init__(self, reports):
        self.reports = {r.id: r for r in reports}

    async def get_by_ids(self, report_ids, owner_id):
        return [r for r in self.reports.values() if r.id in report_ids and owner_id in (None, r.owner_id)]

    async def search(self, owner_id, text, conversation_id, limit):
        return [
            r for r in self.reports.values()
            if owner_id in (None, r.owner_id) and (not text or text.lower() in (r.title + r.body).lower())
        ][:limit]


class FakeDeletionRepository:
    def __init__(self, report_repo):
        self.report_repo = report_repo
        self.proposals = {}

    async def add_proposal(self, proposal):
        for other in self.proposals.values():
            if other.conversation_id == proposal.conversation_id and other.status == DeletionProposalStatus.PENDING:
                other.status = DeletionProposalStatus.CANCELLED
        self.proposals[proposal.id] = proposal
        return proposal

    async def get_proposal(self, proposal_id):
        return self.proposals.get(proposal_id)

    async def close_proposal(self, proposal_id, status):
        proposal = self.proposals[proposal_id]
        if proposal.status != DeletionProposalStatus.PENDING:
            return False
        proposal.status = status
        return True

    async def execute(self, proposal_id, actor_id, owner_id):
        proposal = self.proposals[proposal_id]
        if proposal.status != DeletionProposalStatus.PENDING:
            return None
        deleted = []
        for report_id in proposal.report_ids:
            r = self.report_repo.reports.get(report_id)
            if r and owner_id in (None, r.owner_id):
                deleted.append((r.id, r.title, r.owner_id))
                del self.report_repo.reports[report_id]
        proposal.status = DeletionProposalStatus.EXECUTED
        return deleted


def make_service(*reports):
    report_repo = FakeReportRepository(reports)
    deletion_repo = FakeDeletionRepository(report_repo)
    config = SimpleNamespace(artifacts=ArtifactsConfigModel(deletion_proposal_ttl_s=300))
    svc = DeletionService(ReportService(report_repo, config), deletion_repo, config)
    return svc, report_repo, deletion_repo


def run(coro):
    return asyncio.run(coro)


def test_propose_deletes_nothing_and_only_sees_own_reports():
    svc, reports, _ = make_service(report("user_alice", "Calvin Klein Q1"), report("user_bob", "Calvin Klein Q2"))
    preview = run(svc.propose(ALICE, CONVERSATION, text="calvin", in_conversation=False, report_ids=None))
    assert [r.title for r in preview.reports] == ["Calvin Klein Q1"]
    assert len(reports.reports) == 2


def test_propose_with_no_match_stores_no_proposal():
    svc, _, deletions = make_service(report("user_alice", "Revenue"))
    assert run(svc.propose(ALICE, CONVERSATION, text="nothing like this", in_conversation=False, report_ids=None)) is None
    assert deletions.proposals == {}


def test_propose_by_ids_ignores_other_owners_ids():
    mine, theirs = report("user_alice", "Mine"), report("user_bob", "Theirs")
    svc, _, _ = make_service(mine, theirs)
    preview = run(svc.propose(ALICE, CONVERSATION, text=None, in_conversation=False, report_ids=[mine.id, theirs.id]))
    assert [r.id for r in preview.reports] == [mine.id]


def test_execute_deletes_exactly_the_previewed_reports():
    a, b = report("user_alice", "A"), report("user_alice", "B")
    svc, reports, _ = make_service(a, b)
    preview = run(svc.propose(ALICE, CONVERSATION, text="A", in_conversation=False, report_ids=None))
    deleted = run(svc.execute(ALICE, CONVERSATION, preview.proposal_id))
    assert [d.id for d in deleted] == [a.id]
    assert list(reports.reports) == [b.id]


def test_proposal_is_single_use():
    svc, _, _ = make_service(report("user_alice", "A"))
    preview = run(svc.propose(ALICE, CONVERSATION, text=None, in_conversation=False, report_ids=None))
    run(svc.execute(ALICE, CONVERSATION, preview.proposal_id))
    with pytest.raises(DeletionProposalNotPendingError) as ei:
        run(svc.execute(ALICE, CONVERSATION, preview.proposal_id))
    assert ei.value.status == DeletionProposalStatus.EXECUTED


@pytest.mark.parametrize(
    ("user", "conversation_id"),
    [(BOB, CONVERSATION), (ADMIN, CONVERSATION), (ALICE, uuid4())],
)
def test_proposal_is_bound_to_user_and_conversation(user, conversation_id):
    svc, reports, _ = make_service(report("user_alice", "A"))
    preview = run(svc.propose(ALICE, CONVERSATION, text=None, in_conversation=False, report_ids=None))
    with pytest.raises(DeletionProposalNotFoundError):
        run(svc.execute(user, conversation_id, preview.proposal_id))
    assert len(reports.reports) == 1


def test_expired_proposal_cannot_execute():
    svc, reports, deletions = make_service(report("user_alice", "A"))
    preview = run(svc.propose(ALICE, CONVERSATION, text=None, in_conversation=False, report_ids=None))
    deletions.proposals[preview.proposal_id].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(DeletionProposalNotPendingError) as ei:
        run(svc.execute(ALICE, CONVERSATION, preview.proposal_id))
    assert ei.value.status == DeletionProposalStatus.EXPIRED
    assert deletions.proposals[preview.proposal_id].status == DeletionProposalStatus.EXPIRED
    assert len(reports.reports) == 1


def test_cancelled_proposal_cannot_execute():
    svc, reports, _ = make_service(report("user_alice", "A"))
    preview = run(svc.propose(ALICE, CONVERSATION, text=None, in_conversation=False, report_ids=None))
    run(svc.cancel(ALICE, CONVERSATION, preview.proposal_id))
    with pytest.raises(DeletionProposalNotPendingError):
        run(svc.execute(ALICE, CONVERSATION, preview.proposal_id))
    assert len(reports.reports) == 1


def test_new_proposal_supersedes_the_pending_one():
    svc, _, _ = make_service(report("user_alice", "A"), report("user_alice", "B"))
    first = run(svc.propose(ALICE, CONVERSATION, text="A", in_conversation=False, report_ids=None))
    run(svc.propose(ALICE, CONVERSATION, text="B", in_conversation=False, report_ids=None))
    with pytest.raises(DeletionProposalNotPendingError) as ei:
        run(svc.execute(ALICE, CONVERSATION, first.proposal_id))
    assert ei.value.status == DeletionProposalStatus.CANCELLED


def test_admin_can_delete_any_owners_reports():
    svc, reports, _ = make_service(report("user_alice", "A"), report("user_bob", "B"))
    preview = run(svc.propose(ADMIN, CONVERSATION, text=None, in_conversation=False, report_ids=None))
    assert {r.owner_id for r in preview.reports} == {"user_alice", "user_bob"}
    deleted = run(svc.execute(ADMIN, CONVERSATION, preview.proposal_id))
    assert len(deleted) == 2 and reports.reports == {}
