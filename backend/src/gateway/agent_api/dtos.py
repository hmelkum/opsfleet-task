from uuid import UUID

from src.core.fastapi.dtos.base import BaseDTO
from src.gateway.models.chat import MessageRole


class AgentHistoryMessageDTO(BaseDTO):
    role: MessageRole
    content: str


class PostAgentChatRequestDTO(BaseDTO):
    """The agent is stateless: every request carries the recent transcript."""
    conversation_id: UUID
    turn_id: UUID
    message: str
    history: list[AgentHistoryMessageDTO] = []
