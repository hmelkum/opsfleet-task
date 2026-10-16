from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ReportModel(BaseModel):
    id: UUID
    owner_id: str
    title: str
    body: str
    created_at: datetime
