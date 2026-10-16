"""
Chat gateway.

Owns conversations and the transcript, and relays turns to the stateless
agent: each request carries the full transcript (a stable, growing prefix, so
the model's prompt cache keeps working), and the agent's NDJSON stream is
passed through while the answer is collected for the transcript.

A deletion confirmation never reaches the agent. The gateway executes or
cancels the proposal through the deletion port, and records both the user's
decision and the outcome in the transcript, so the next turn sees what
happened.

Answer text is PII-masked on the way out (the last of three PII layers), and a
circuit breaker stops calling an agent that keeps failing. Either way the
client gets a safe error chunk instead of a broken stream.
"""
import logging
import time
from collections.abc import AsyncGenerator
from uuid import UUID

from httpx import HTTPError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from src.core.deletions.port import (
    DeletedReport,
    DeletionPort,
    DeletionProposalNotFoundError,
    DeletionProposalNotPendingError,
)
from src.core.fastapi.dependencies.wrappers import InjectPlaceholder
from src.core.identity.users import UserContext
from src.core.observability.events import emit
from src.core.pii.masking import StreamingMasker
from src.gateway.agent_api.circuit_breaker import CircuitBreaker
from src.gateway.agent_api.client import AgentAPIClient
from src.gateway.agent_api.dtos import AgentHistoryMessageDTO, PostAgentChatRequestDTO
from src.gateway.dtos.chat import ChatConfirmationDTO, PostChatRequestDTO
from src.gateway.entities import ConversationEntity, MessageEntity
from src.gateway.exceptions import ConversationNotFoundError
from src.gateway.models.chat import ChatChunkModel, ChatChunkType, MessageRole
from src.gateway.repositories.conversations import ConversationRepository
from src.gateway.repositories.messages import MessageRepository

logger = logging.getLogger(__name__)

AGENT_UNAVAILABLE_MESSAGE = "The assistant is temporarily unavailable. Please try again in a moment."
DELETION_UNAVAILABLE_MESSAGE = "The report library is temporarily unavailable, so nothing was deleted. Please try again."
DELETION_DECLINED_MESSAGE = "Okay, nothing was deleted."
DELETION_HANDLED_MESSAGE = (
    "Nothing was deleted: this deletion request has expired or was already handled. "
    "Ask again if you still want to delete those reports."
)
DELETION_NO_LONGER_EXISTS_MESSAGE = "Nothing was deleted: those reports no longer exist."


class ChatService:
    def __init__(
        self,
        conversation_repo: ConversationRepository = InjectPlaceholder(),
        message_repo: MessageRepository = InjectPlaceholder(),
        agent_api_client: AgentAPIClient = InjectPlaceholder(),
        circuit_breaker: CircuitBreaker = InjectPlaceholder(),
        deletion_port: DeletionPort = InjectPlaceholder()
    ) -> None:
        self._conversation_repo = conversation_repo
        self._message_repo = message_repo
        self._agent_api_client = agent_api_client
        self._circuit_breaker = circuit_breaker
        self._deletion_port = deletion_port

    async def open_conversation(self, user: UserContext, conversation_id: UUID | None) -> UUID:
        """Starts a new conversation, or returns ``conversation_id`` if the user owns it."""
        if conversation_id is None:
            conversation = await self._conversation_repo.add(ConversationEntity(user_id=user.user_id))
            return conversation.id

        conversation = await self._conversation_repo.get(conversation_id)
        if conversation is None or conversation.user_id != user.user_id:
            raise ConversationNotFoundError()
        return conversation.id

    async def stream(
        self,
        user: UserContext,
        conversation_id: UUID,
        dto: PostChatRequestDTO
    ) -> AsyncGenerator[ChatChunkModel, None]:
        user_message = MessageEntity(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=self._user_content(dto)
        )
        turn_id = user_message.id  # the turn is identified by the user's message; feedback points at it
        yield ChatChunkModel(
            type=ChatChunkType.CONVERSATION,
            content={"conversationId": str(conversation_id), "turnId": str(turn_id)}
        )

        if dto.confirmation is not None:
            await self._message_repo.add(user_message)
            async for chunk in self._decide_deletion(user, conversation_id, turn_id, dto.confirmation):
                yield chunk
            return

        history = await self._message_repo.get_all(conversation_id)
        await self._message_repo.add(user_message)
        async for chunk in self._answer(user, conversation_id, turn_id, dto, history):
            yield chunk

    async def _decide_deletion(
        self,
        user: UserContext,
        conversation_id: UUID,
        turn_id: UUID,
        decision: ChatConfirmationDTO
    ) -> AsyncGenerator[ChatChunkModel, None]:
        """Executes or cancels the proposal the user answered in the CLI. No agent or model involved."""
        started = time.monotonic()
        text, label, deleted_count = await self._resolve_deletion(user, conversation_id, decision)

        masker = StreamingMasker()
        released = masker.feed(text) + masker.flush()
        yield ChatChunkModel(type=ChatChunkType.ANSWER, content=released)
        # The transcript gets the same text the user saw, so the next turn knows what happened.
        await self._message_repo.add(
            MessageEntity(conversation_id=conversation_id, role=MessageRole.ASSISTANT, content=released)
        )

        emit(
            "deletion_decision",
            conversation_id=str(conversation_id),
            turn_id=str(turn_id),
            user_id=user.user_id,
            proposal_id=str(decision.proposal_id),
            confirmed=decision.confirmed,
            outcome=label,
            reports=deleted_count,
        )
        emit(
            "chat_turn",
            conversation_id=str(conversation_id),
            turn_id=str(turn_id),
            user_id=user.user_id,
            kind="confirmation",
            outcome=label,
            duration_ms=int((time.monotonic() - started) * 1000),
            pii_masked=dict(masker.counts),
        )

    async def _resolve_deletion(
        self,
        user: UserContext,
        conversation_id: UUID,
        decision: ChatConfirmationDTO
    ) -> tuple[str, str, int]:
        """The outcome text, a short label for logs, and how many reports were deleted. Never raises."""
        try:
            if decision.confirmed:
                deleted = await self._deletion_port.execute(user, conversation_id, decision.proposal_id)
                return self._deleted_text(deleted), "executed" if deleted else "empty", len(deleted)
            await self._deletion_port.cancel(user, conversation_id, decision.proposal_id)
            return DELETION_DECLINED_MESSAGE, "cancelled", 0
        except DeletionProposalNotFoundError:
            label = "not_found"
        except DeletionProposalNotPendingError as e:
            label = e.status
        except SQLAlchemyError as e:
            logger.error("deletion_failed proposal_id=%s error=%r", decision.proposal_id, e)
            return DELETION_UNAVAILABLE_MESSAGE, "unavailable", 0

        # Declining a proposal that is already gone still leaves nothing deleted.
        text = DELETION_DECLINED_MESSAGE if not decision.confirmed else DELETION_HANDLED_MESSAGE
        return text, label, 0

    @staticmethod
    def _deleted_text(deleted: list[DeletedReport]) -> str:
        if not deleted:
            return DELETION_NO_LONGER_EXISTS_MESSAGE
        lines = "\n".join(f"- {report.title}" for report in deleted)
        return f"Deleted {len(deleted)} report(s):\n{lines}"

    async def _answer(
        self,
        user: UserContext,
        conversation_id: UUID,
        turn_id: UUID,
        dto: PostChatRequestDTO,
        history: list[MessageEntity]
    ) -> AsyncGenerator[ChatChunkModel, None]:
        started = time.monotonic()
        request = PostAgentChatRequestDTO(
            conversation_id=conversation_id,
            turn_id=turn_id,
            message=dto.message,
            history=[
                AgentHistoryMessageDTO(role=MessageRole(message.role), content=message.content)
                for message in history
            ]
        )

        answer_parts: list[str] = []
        masker = StreamingMasker()
        # Thoughts are derived from query results and tool arguments, so they are masked like answers.
        # They keep their own masker, because a thought and an answer can split a value between them.
        thought_masker = StreamingMasker()
        tool_calls = 0
        confirmation_required = False
        outcome = "answered"

        def flush_answer() -> ChatChunkModel | None:
            released = masker.flush()
            if not released:
                return None
            answer_parts.append(released)
            return ChatChunkModel(type=ChatChunkType.ANSWER, content=released)

        def flush_thought() -> ChatChunkModel | None:
            released = thought_masker.flush()
            return ChatChunkModel(type=ChatChunkType.THOUGHT, content=released) if released else None

        if not self._circuit_breaker.allow_request():
            outcome = "circuit_open"
            yield ChatChunkModel(type=ChatChunkType.ERROR, content=AGENT_UNAVAILABLE_MESSAGE)
        else:
            try:
                async for line in self._agent_api_client.stream_chat(user.user_id, request):
                    chunk = ChatChunkModel.model_validate_json(line)
                    if chunk.type == ChatChunkType.THOUGHT:
                        if released := thought_masker.feed(str(chunk.content)):
                            yield ChatChunkModel(type=ChatChunkType.THOUGHT, content=released)
                        continue
                    if pending := flush_thought():  # the reasoning comes before whatever follows it
                        yield pending
                    if chunk.type == ChatChunkType.TITLE:  # stored for /history, not forwarded
                        await self._conversation_repo.set_title(conversation_id, str(chunk.content)[:200])
                        continue
                    if chunk.type == ChatChunkType.ANSWER:
                        released = masker.feed(str(chunk.content))
                        if released:
                            answer_parts.append(released)
                            yield ChatChunkModel(type=ChatChunkType.ANSWER, content=released)
                        continue

                    if pending := flush_answer():  # keep the answer text in order with other chunks
                        yield pending
                    match chunk.type:
                        case ChatChunkType.TOOL_CALL:
                            tool_calls += 1
                        case ChatChunkType.CONFIRMATION_REQUIRED:
                            confirmation_required = True
                        case ChatChunkType.ERROR:
                            outcome = "agent_error"
                    yield chunk
                self._circuit_breaker.record_success()
            except HTTPError as e:
                logger.error("agent_stream_failed conversation_id=%s error=%r", conversation_id, e)
                self._circuit_breaker.record_failure()
                outcome = "agent_unavailable"
                if pending := flush_answer():
                    yield pending
                yield ChatChunkModel(type=ChatChunkType.ERROR, content=AGENT_UNAVAILABLE_MESSAGE)
            except ValidationError as e:
                logger.error("agent_stream_malformed conversation_id=%s error=%r", conversation_id, e)
                outcome = "agent_unavailable"
                if pending := flush_answer():
                    yield pending
                yield ChatChunkModel(type=ChatChunkType.ERROR, content=AGENT_UNAVAILABLE_MESSAGE)

        if pending := flush_thought():
            yield pending
        if pending := flush_answer():
            yield pending

        if answer_parts:
            await self._message_repo.add(
                MessageEntity(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content="".join(answer_parts)
                )
            )

        emit(
            "chat_turn",
            conversation_id=str(conversation_id),
            turn_id=str(turn_id),
            user_id=user.user_id,
            kind="message",
            outcome=outcome,
            duration_ms=int((time.monotonic() - started) * 1000),
            history_messages=len(history),
            tool_calls=tool_calls,
            confirmation_required=confirmation_required,
            answer_chars=sum(len(part) for part in answer_parts),
            pii_masked=dict(masker.counts + thought_masker.counts),
        )

    @staticmethod
    def _user_content(dto: PostChatRequestDTO) -> str:
        if dto.message is not None:
            return dto.message
        assert dto.confirmation is not None
        return "Confirmed the deletion." if dto.confirmation.confirmed else "Declined the deletion."
