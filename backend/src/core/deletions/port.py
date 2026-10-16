"""
Contract between the chat gateway and the artifacts module for hard deletion.

The gateway executes or cancels a proposal after the user answered the CLI's
structured confirmation, and records the outcome in the transcript. The
artifacts module implements the port. It lives in ``core`` so the two modules
never import each other.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from src.core.identity.users import UserContext


@dataclass(frozen=True)
class DeletedReport:
    id: UUID
    title: str
    owner_id: str


class DeletionProposalNotFoundError(Exception):
    """No pending proposal with this id for this user and conversation."""


class DeletionProposalNotPendingError(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(f"Deletion proposal is {status}.")
        self.status = status


class DeletionPort(ABC):
    @abstractmethod
    async def execute(self, user: UserContext, conversation_id: UUID, proposal_id: UUID) -> list[DeletedReport]:
        """Deletes the proposal's reports. Single use: a proposal can be executed or cancelled once."""

    @abstractmethod
    async def cancel(self, user: UserContext, conversation_id: UUID, proposal_id: UUID) -> None:
        """Closes a pending proposal without deleting anything."""
