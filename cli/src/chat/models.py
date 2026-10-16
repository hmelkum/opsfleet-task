from enum import StrEnum, auto


class ChatChunkType(StrEnum):
    CONVERSATION = auto()  # first chunk of every stream: the conversation id
    ANSWER = auto()  # a piece of the assistant's text
    THOUGHT = auto()  # a piece of the model's reasoning summary (shown with /thoughts)
    TOOL_CALL = auto()  # a tool the agent called, with its full arguments (shown with /debug)
    CONFIRMATION_REQUIRED = auto()  # a deletion preview the user must confirm or decline
    ERROR = auto()  # a safe, user-facing error message
