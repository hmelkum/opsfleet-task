"""Names a conversation from its first message, so /history can list it."""
import logging
import time

from langchain_core.language_models import BaseChatModel
from pydantic import Field

from src.core.llm.structured_output.models.base import BaseStructuredOutput
from src.core.observability.events import emit

logger = logging.getLogger(__name__)

_TITLE_PROMPT = (
    "Write a short title, at most 6 words, for a conversation with a retail data analyst "
    "that starts with the message below. Plain words only: no quotes, no emoji, no trailing "
    "punctuation.\n\nMessage:\n{message}"
)

_MAX_TITLE_CHARS = 80


class ConversationTitleOutput(BaseStructuredOutput):
    # Not named ``title``: the base model's schema cleanup removes every "title" key.
    conversation_title: str = Field(description="A short title for the conversation, at most 6 words.")


class ConversationTitleService:
    def __init__(self, llm: BaseChatModel) -> None:
        self._llm = llm.with_structured_output(ConversationTitleOutput)

    async def generate(self, message: str, **event_ids: str | None) -> str | None:
        """The title, or None if it could not be generated. Never raises: a title is optional."""
        started = time.monotonic()
        try:
            output = await self._llm.ainvoke(_TITLE_PROMPT.format(message=message[:2000]))
            title = " ".join(output.conversation_title.split()).strip(" .\"'")[:_MAX_TITLE_CHARS]
        except Exception as e:
            logger.warning("conversation_title_failed error=%r", e)
            emit("conversation_title", **event_ids, outcome="error", error=type(e).__name__,
                 duration_ms=int((time.monotonic() - started) * 1000))
            return None
        emit("conversation_title", **event_ids, outcome="ok" if title else "empty",
             duration_ms=int((time.monotonic() - started) * 1000))
        return title or None
