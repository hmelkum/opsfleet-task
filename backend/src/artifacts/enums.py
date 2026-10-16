from enum import StrEnum, auto


class ArtifactKind(StrEnum):
    REPORT = auto()


class DeletionProposalStatus(StrEnum):
    PENDING = auto()
    EXECUTED = auto()
    CANCELLED = auto()
    EXPIRED = auto()
