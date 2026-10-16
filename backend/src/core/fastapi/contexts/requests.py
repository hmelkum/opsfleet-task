from fastapi import Header
from pydantic import BaseModel, Field, field_validator

from src.core.identity.users import UserContext, parse_user_id


class RequestContext(BaseModel):
    user_id: str = Field(..., alias="X-User-Id")

    @field_validator("user_id", mode="after")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        return parse_user_id(v).user_id


class RequestContextService:
    def __init__(self, context: RequestContext = Header(...)) -> None:
        self._context = context
        self._user = parse_user_id(context.user_id)

    @property
    def user(self) -> UserContext:
        return self._user
