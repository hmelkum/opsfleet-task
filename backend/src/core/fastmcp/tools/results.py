from enum import StrEnum, auto
from typing import Literal

from pydantic import BaseModel


class ToolResult(BaseModel):
    pass


class SuccessToolResult(ToolResult):
    success: Literal[True] = True


class RetryGuidance(StrEnum):
    DO_NOT_RETRY = auto()
    SAME_INPUT = auto()
    DIFFERENT_INPUT = auto()


class ErrorToolResult(ToolResult):
    success: Literal[False] = False
    error: str
    retry: RetryGuidance