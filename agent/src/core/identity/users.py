"""
Caller identity.

The CLI sends ``X-User-Id``: ``admin`` for the administrator, or
``user_<username>`` for everyone else. The role is parsed from the id. There
is no authentication yet; the id is trusted as sent.
"""
import re
from enum import StrEnum, auto

from pydantic import BaseModel, ConfigDict

ADMIN_USER_ID = "admin"

_USER_ID_PATTERN = re.compile(r"^user_[A-Za-z0-9._-]{1,64}$")


class Role(StrEnum):
    ADMIN = auto()
    USER = auto()


class UserContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    role: Role

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN


def parse_user_id(user_id: str) -> UserContext:
    user_id = (user_id or "").strip()
    if user_id == ADMIN_USER_ID:
        return UserContext(user_id=user_id, role=Role.ADMIN)
    if _USER_ID_PATTERN.fullmatch(user_id):
        return UserContext(user_id=user_id, role=Role.USER)
    raise ValueError(f"User ID must be '{ADMIN_USER_ID}' or 'user_<username>'.")
