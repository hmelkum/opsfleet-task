import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from src.artifacts.entities import ArtifactEntity
from src.artifacts.enums import ArtifactKind
from src.artifacts.models.reports import ReportModel
from src.artifacts.services.artifacts import ArtifactService
from src.core.identity.users import parse_user_id


def artifact(owner_id: str, title: str) -> ArtifactEntity:
    entity = ArtifactEntity(kind=ArtifactKind.REPORT, ref_id=uuid4(), owner_id=owner_id, conversation_id=uuid4(), title=title)
    entity.created_at = datetime.now(UTC)
    return entity


class FakeArtifactRepository:
    def __init__(self, *items):
        self.items = list(items)

    async def list(self, owner_id, limit):
        return [a for a in self.items if owner_id in (None, a.owner_id)][:limit]

    async def get(self, artifact_id, owner_id):
        return next((a for a in self.items if a.id == artifact_id and owner_id in (None, a.owner_id)), None)


class FakeReportService:
    async def get(self, user, report_id):
        return ReportModel(id=report_id, owner_id="x", title="t", body="## Summary", created_at=datetime.now(UTC))


def make_service(*items):
    return ArtifactService(FakeArtifactRepository(*items), FakeReportService())


def test_users_list_their_own_artifacts_admin_lists_all():
    svc = make_service(artifact("user_alice", "A"), artifact("user_bob", "B"))
    assert [a.title for a in asyncio.run(svc.list(parse_user_id("user_alice")))] == ["A"]
    assert {a.title for a in asyncio.run(svc.list(parse_user_id("admin")))} == {"A", "B"}


def test_get_returns_report_body_and_hides_others_artifacts():
    mine, theirs = artifact("user_alice", "A"), artifact("user_bob", "B")
    svc = make_service(mine, theirs)
    detail = asyncio.run(svc.get(parse_user_id("user_alice"), mine.id))
    assert detail.artifact.title == "A" and detail.content == {"body": "## Summary"}
    assert asyncio.run(svc.get(parse_user_id("user_alice"), theirs.id)) is None
    assert asyncio.run(svc.get(parse_user_id("admin"), theirs.id)) is not None
