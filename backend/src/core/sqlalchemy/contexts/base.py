from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession


class BaseDBContext(ABC):
    @abstractmethod
    def session(self, *, schema: str | None = None) -> AsyncSession:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...

    @abstractmethod
    async def is_healthy(self) -> bool:
        ...