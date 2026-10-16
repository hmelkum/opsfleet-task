from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass

from src.core.sqlalchemy.entities.base import NAMING_CONVENTION, _TablenameMixin


class BaseChatEntity(_TablenameMixin, AsyncAttrs, MappedAsDataclass, DeclarativeBase):
    metadata = MetaData(
        schema="chat",
        naming_convention=NAMING_CONVENTION
    )
