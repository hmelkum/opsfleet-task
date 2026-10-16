from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from src.core.sqlalchemy.contexts.base import BaseDBContext
from src.gateway.entities import MessageEntity


class MessageRepository:
    def __init__(self, db_context: BaseDBContext) -> None:
        self._db_context = db_context

    async def add(self, message: MessageEntity) -> MessageEntity:
        async with self._db_context.session() as session:
            async with session.begin():
                session.add(message)
            return message

    async def get_all(self, conversation_id: UUID) -> Sequence[MessageEntity]:
        """The whole transcript, oldest first."""
        stmt = (
            select(MessageEntity)
            .where(MessageEntity.conversation_id == conversation_id)
            .order_by(MessageEntity.created_at, MessageEntity.id)
        )
        async with self._db_context.session() as session:
            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_user_message(self, conversation_id: UUID, message_id: UUID) -> MessageEntity | None:
        stmt = (
            select(MessageEntity)
            .where(MessageEntity.id == message_id)
            .where(MessageEntity.conversation_id == conversation_id)
            .where(MessageEntity.role == "user")
        )
        async with self._db_context.session() as session:
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
