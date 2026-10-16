from sqlalchemy.dialects.postgresql import insert

from src.core.sqlalchemy.contexts.base import BaseDBContext
from src.gateway.entities import FeedbackEntity


class FeedbackRepository:
    def __init__(self, db_context: BaseDBContext) -> None:
        self._db_context = db_context

    async def upsert(self, feedback: FeedbackEntity) -> None:
        """One rating per turn: rating again replaces the previous one."""
        stmt = insert(FeedbackEntity).values(
            id=feedback.id,
            turn_id=feedback.turn_id,
            conversation_id=feedback.conversation_id,
            user_id=feedback.user_id,
            rating=feedback.rating,
            comment=feedback.comment
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[FeedbackEntity.turn_id],
            set_={"rating": stmt.excluded.rating, "comment": stmt.excluded.comment}
        )
        async with self._db_context.session() as session:
            async with session.begin():
                await session.execute(stmt)
