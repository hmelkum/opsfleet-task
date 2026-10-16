from uuid import UUID

from src.artifacts.entities import ArtifactEntity
from src.artifacts.enums import ArtifactKind
from src.artifacts.models.artifacts import ArtifactDetailModel, ArtifactModel
from src.artifacts.repositories.artifacts import ArtifactRepository
from src.artifacts.services.reports import ReportService
from src.core.fastapi.dependencies.wrappers import InjectPlaceholder
from src.core.identity.users import UserContext


class ArtifactService:
    """Read access to the artifact library. Users see their own artifacts; admin sees everyone's."""

    def __init__(
        self,
        artifact_repo: ArtifactRepository = InjectPlaceholder(),
        report_svc: ReportService = InjectPlaceholder()
    ) -> None:
        self._artifact_repo = artifact_repo
        self._report_svc = report_svc

    async def list(self, user: UserContext, limit: int = 100) -> list[ArtifactModel]:
        entities = await self._artifact_repo.list(self._owner_filter(user), limit)
        return [self._to_model(entity) for entity in entities]

    async def get(self, user: UserContext, artifact_id: UUID) -> ArtifactDetailModel | None:
        entity = await self._artifact_repo.get(artifact_id, self._owner_filter(user))
        if entity is None:
            return None

        match ArtifactKind(entity.kind):
            case ArtifactKind.REPORT:
                report = await self._report_svc.get(user, entity.ref_id)
                if report is None:
                    return None
                content = {"body": report.body}
        return ArtifactDetailModel(artifact=self._to_model(entity), content=content)

    @staticmethod
    def _to_model(entity: ArtifactEntity) -> ArtifactModel:
        return ArtifactModel(
            id=entity.id,
            kind=ArtifactKind(entity.kind),
            ref_id=entity.ref_id,
            owner_id=entity.owner_id,
            conversation_id=entity.conversation_id,
            title=entity.title,
            created_at=entity.created_at
        )

    @staticmethod
    def _owner_filter(user: UserContext) -> str | None:
        return None if user.is_admin else user.user_id
