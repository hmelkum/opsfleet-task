from typing import Annotated
from uuid import UUID

from pydantic import StringConstraints

from src.core.fastapi.dtos.base import BaseDTO
from src.gateway.models.chat import FeedbackRating

FeedbackCommentStr = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=2000
    )
]


class PostFeedbackRequestDTO(BaseDTO):
    conversation_id: UUID
    turn_id: UUID
    rating: FeedbackRating
    comment: FeedbackCommentStr | None = None


class FeedbackErrorResponseDTO(BaseDTO):
    detail: str
