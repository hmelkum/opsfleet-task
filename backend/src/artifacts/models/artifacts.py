from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from src.artifacts.enums import ArtifactKind


class ArtifactModel(BaseModel):
    id: UUID
    kind: ArtifactKind
    ref_id: UUID
    owner_id: str
    conversation_id: UUID
    title: str
    created_at: datetime


class ArtifactDetailModel(BaseModel):
    artifact: ArtifactModel
    # Kind-specific content, e.g. {"body": ...} for a report
    content: dict[str, Any]
