from enum import StrEnum, auto
from typing import Any

from pydantic import BaseModel


class MessageRole(StrEnum):
    USER = auto()
    ASSISTANT = auto()


class ChatChunkType(StrEnum):
    ANSWER = auto()  # a piece of the assistant's text
    THOUGHT = auto()  # a piece of the model's reasoning summary (not part of the answer or the transcript)
    TOOL_CALL = auto()  # a tool the agent called, with its full arguments (the client decides what to show)
    CONFIRMATION_REQUIRED = auto()  # a deletion preview the user must confirm or decline
    ERROR = auto()  # a safe, user-facing error message
    TITLE = auto()  # the conversation title, sent on the first turn only


class ChatChunkModel(BaseModel):
    """One NDJSON line of the chat stream, the contract between agent, gateway and CLI."""
    type: ChatChunkType
    content: Any
