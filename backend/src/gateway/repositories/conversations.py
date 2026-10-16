from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import Row, func, select, update
from sqlalchemy.orm import aliased

from src.core.sqlalchemy.contexts.base import BaseDBContext
from src.gateway.entities import ConversationEntity, MessageEntity


class ConversationRepository:
    def __init__(self, db_context: BaseDBContext) -> None:
        self._db_context = db_context

    async def add(self, conversation: ConversationEntity) -> ConversationEntity:
        async with self._db_context.session() as session:
            async with session.begin():
                session.add(conversation)
            await session.refresh(conversation)
            return conversation

    async def get(self, conversation_id: UUID) -> ConversationEntity | None:
        async with self._db_context.session() as session:
            return await session.get(ConversationEntity, conversation_id)

    async def set_title(self, conversation_id: UUID, title: str) -> None:
        """Sets the title once; a conversation keeps its first title."""
        async with self._db_context.session() as session:
            async with session.begin():
                await session.execute(
                    update(ConversationEntity)
                    .where(ConversationEntity.id == conversation_id)
                    .where(ConversationEntity.title.is_(None))
                    .values(title=title)
                )

    async def list_by_user(
        self,
        user_id: str,
        limit: int
    ) -> Sequence[Row[tuple[UUID, str | None, str | None, int, datetime, datetime]]]:
        """The user's conversations that have messages, most recently active first.

        Each row: id, title, first user message, message count, created_at, last message time.
        """
        first = aliased(MessageEntity)
        first_message = (
            select(first.content)
            .where(first.conversation_id == ConversationEntity.id)
            .where(first.role == "user")
            .order_by(first.created_at)
            .limit(1)
            .correlate(ConversationEntity)
            .scalar_subquery()
        )
        last_message_at = func.max(MessageEntity.created_at)
        stmt = (
            select(
                ConversationEntity.id,
                ConversationEntity.title,
                first_message,
                func.count(MessageEntity.id),
                ConversationEntity.created_at,
                last_message_at,
            )
            .join(MessageEntity, MessageEntity.conversation_id == ConversationEntity.id)
            .where(ConversationEntity.user_id == user_id)
            .group_by(ConversationEntity.id)
            .order_by(last_message_at.desc())
            .limit(limit)
        )
        async with self._db_context.session() as session:
            result = await session.execute(stmt)
            return result.all()
