from enum import StrEnum, auto


class LLMType(StrEnum):
    MAIN = auto()
    FALLBACK = auto()
    TITLE = auto()
