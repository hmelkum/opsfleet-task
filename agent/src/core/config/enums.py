from enum import StrEnum, auto


class EnvType(StrEnum):
    DEV = auto()
    TEST = auto()
    QA = auto()
    PROD = auto()