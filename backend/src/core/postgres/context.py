import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.postgres.config import BasePostgresDBConfigService
from src.core.sqlalchemy.contexts.base import BaseDBContext

logger = logging.getLogger(__name__)


class PostgresDBContext(BaseDBContext):
    def __init__(self, db_config_service: BasePostgresDBConfigService) -> None:
        config = db_config_service.postgres

        self._engine: AsyncEngine = create_async_engine(
            url=config.url,
            pool_pre_ping=True,
        )

        self._session_factory = async_sessionmaker(
            expire_on_commit=False,
            autoflush=False,
        )

    def session(self, *, schema: str | None = None) -> AsyncSession:
        if not schema:
            return self._session_factory(bind=self._engine)
        
        return self._session_factory(
            bind=self._engine.execution_options(
                schema_translate_map={"tenant": schema}
            )
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def is_healthy(self) -> bool:
        try:
            async with self.session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as ex:
            logger.exception("PostgresDBContext health check failed: %s", ex)
            return False