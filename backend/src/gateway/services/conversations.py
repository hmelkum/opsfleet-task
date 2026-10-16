from uuid import UUID

from src.core.fastapi.dependencies.wrappers import InjectPlaceholder
from src.core.identity.users import UserContext
from src.gateway.exceptions import ConversationNotFoundError
from src.gateway.models.chat import MessageRole
from src.gateway.models.conversations import ConversationSummaryModel, MessageModel
from src.gateway.repositories.conversations import ConversationRepository
from src.gateway.repositories.messages import MessageRepository

_UNTITLED_CHARS = 60


class ConversationService:
    """Conversations are private: everyone, the admin included, lists only their own."""

    def __init__(
        self,
        conversation_repo: ConversationRepository = InjectPlaceholder(),
        message_repo: MessageRepository = InjectPlaceholder()
    ) -> None:
        self._conversation_repo = conversation_repo
        self._message_repo = message_repo

    async def get_summaries(self, user: UserContext, limit: int = 50) -> list[ConversationSummaryModel]:
        rows = await self._conversation_repo.list_by_user(user.user_id, limit)
        return [
            ConversationSummaryModel(
                id=conversation_id,
                title=title or self._untitled(first_message),
                message_count=message_count,
                created_at=created_at,
                last_message_at=last_message_at
            )
            for conversation_id, title, first_message, message_count, created_at, last_message_at in rows
        ]

    async def get_messages(self, user: UserContext, conversation_id: UUID) -> list[MessageModel]:
        """The whole transcript of one of the user's own conversations, oldest first."""
        conversation = await self._conversation_repo.get(conversation_id)
        if conversation is None or conversation.user_id != user.user_id:
            raise ConversationNotFoundError()
        messages = await self._message_repo.get_all(conversation_id)
        return [
            MessageModel(role=MessageRole(message.role), content=message.content, created_at=message.created_at)
            for message in messages
        ]

    @staticmethod
    def _untitled(first_message: str | None) -> str:
        """Falls back to the first message when no title was generated."""
        text = " ".join((first_message or "Untitled").split())
        return text if len(text) <= _UNTITLED_CHARS else text[:_UNTITLED_CHARS - 1] + "…"
