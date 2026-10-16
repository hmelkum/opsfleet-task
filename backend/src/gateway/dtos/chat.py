from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import StringConstraints, model_validator

from src.core.fastapi.dtos.base import BaseDTO

ChatMessageStr = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=8000
    )
]


class ChatConfirmationDTO(BaseDTO):
    proposal_id: UUID
    confirmed: bool


class PostChatRequestDTO(BaseDTO):
    """Either a new ``message`` or the user's ``confirmation`` of a pending deletion."""
    conversation_id: UUID | None = None
    message: ChatMessageStr | None = None
    confirmation: ChatConfirmationDTO | None = None

    @model_validator(mode="after")
    def validate_message_or_confirmation(self) -> Self:
        if (self.message is None) == (self.confirmation is None):
            raise ValueError("Exactly one of 'message' or 'confirmation' is required.")
        if self.confirmation is not None and self.conversation_id is None:
            raise ValueError("'conversationId' is required with a confirmation.")
        return self


class ToolCallDTO(BaseDTO):
    name: str
    args: dict[str, Any]


class PostChatResponseDTO(BaseDTO):
    conversation_id: UUID
    turn_id: UUID
    answer: str
    tool_calls: list[ToolCallDTO] = []
    confirmation: dict[str, Any] | None = None
    error: str | None = None


class ChatErrorResponseDTO(BaseDTO):
    detail: str
