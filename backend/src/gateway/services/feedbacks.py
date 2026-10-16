from uuid import UUID

from src.core.fastapi.dependencies.wrappers import InjectPlaceholder
from src.core.identity.users import UserContext
from src.core.observability.events import emit
from src.gateway.entities import FeedbackEntity
from src.gateway.exceptions import ConversationNotFoundError, TurnNotFoundError
from src.gateway.models.chat import FeedbackRating
from src.gateway.repositories.conversations import ConversationRepository
from src.gateway.repositories.feedbacks import FeedbackRepository
from src.gateway.repositories.messages import MessageRepository


class FeedbackService:
    def __init__(
        self,
        conversation_repo: ConversationRepository = InjectPlaceholder(),
        message_repo: MessageRepository = InjectPlaceholder(),
        feedback_repo: FeedbackRepository = InjectPlaceholder()
    ) -> None:
        self._conversation_repo = conversation_repo
        self._message_repo = message_repo
        self._feedback_repo = feedback_repo

    async def rate(
        self,
        user: UserContext,
        conversation_id: UUID,
        turn_id: UUID,
        rating: FeedbackRating,
        comment: str | None
    ) -> None:
        """Rates a turn of the user's own conversation. Feeds the learning loop and the metrics."""
        conversation = await self._conversation_repo.get(conversation_id)
        if conversation is None or conversation.user_id != user.user_id:
            raise ConversationNotFoundError()
        if await self._message_repo.get_user_message(conversation_id, turn_id) is None:
            raise TurnNotFoundError()

        await self._feedback_repo.upsert(
            FeedbackEntity(
                turn_id=turn_id,
                conversation_id=conversation_id,
                user_id=user.user_id,
                rating=rating,
                comment=comment
            )
        )
        emit(
            "feedback",
            conversation_id=str(conversation_id),
            turn_id=str(turn_id),
            user_id=user.user_id,
            rating=rating.value,
            has_comment=bool(comment),
        )
