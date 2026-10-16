from datetime import datetime
from typing import Any
from uuid import UUID

from src.artifacts.enums import ArtifactKind
from src.core.fastapi.dtos.base import BaseDTO


class ArtifactDTO(BaseDTO):
    id: UUID
    kind: ArtifactKind
    owner_id: str
    conversation_id: UUID
    title: str
    created_at: datetime


class GetArtifactsResponseDTO(BaseDTO):
    artifacts: list[ArtifactDTO]


class GetArtifactResponseDTO(BaseDTO):
    artifact: ArtifactDTO
    content: dict[str, Any]


class ArtifactErrorResponseDTO(BaseDTO):
    detail: str
