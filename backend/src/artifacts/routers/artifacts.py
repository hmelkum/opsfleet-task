from uuid import UUID

from fastapi import APIRouter, Path, Response, status
from fastapi.responses import JSONResponse

from src.artifacts.dtos.artifacts import (
    ArtifactDTO,
    ArtifactErrorResponseDTO,
    GetArtifactResponseDTO,
    GetArtifactsResponseDTO,
)
from src.artifacts.models.artifacts import ArtifactModel
from src.artifacts.services.artifacts import ArtifactService
from src.core.fastapi.contexts.requests import RequestContextService
from src.core.fastapi.dependencies.wrappers import Inject, InjectScoped

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])


def _to_dto(artifact: ArtifactModel) -> ArtifactDTO:
    return ArtifactDTO(
        id=artifact.id,
        kind=artifact.kind,
        owner_id=artifact.owner_id,
        conversation_id=artifact.conversation_id,
        title=artifact.title,
        created_at=artifact.created_at
    )


@router.get(
    "",
    summary="List artifacts: the caller's own, or everyone's for the admin",
    response_model=GetArtifactsResponseDTO,
)
async def get_artifacts(
    ctx: RequestContextService = InjectScoped(),
    artifact_svc: ArtifactService = Inject()
) -> Response:
    artifacts = await artifact_svc.list(ctx.user)
    return JSONResponse(GetArtifactsResponseDTO(artifacts=[_to_dto(a) for a in artifacts]).dto_dump())


@router.get(
    "/{artifact_id}",
    summary="Get one artifact with its content",
    response_model=GetArtifactResponseDTO,
    responses={404: {"description": "Artifact not found for this user."}},
)
async def get_artifact(
    artifact_id: UUID = Path(...),
    ctx: RequestContextService = InjectScoped(),
    artifact_svc: ArtifactService = Inject()
) -> Response:
    detail = await artifact_svc.get(ctx.user, artifact_id)
    if detail is None:
        return JSONResponse(
            ArtifactErrorResponseDTO(detail="Artifact not found.").dto_dump(),
            status_code=status.HTTP_404_NOT_FOUND
        )
    return JSONResponse(
        GetArtifactResponseDTO(artifact=_to_dto(detail.artifact), content=detail.content).dto_dump()
    )
