from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, SecretStr


class LLMConfigModel(BaseModel):
    main_model: str = "gemini-3.8-flash"
    # Used when the main model keeps failing (429/5xx) after retries: cheaper, and a different model
    fallback_model: str = "gemini-3.5-flash-lite"
    # Small and fast: names a conversation from its first message
    title_model: str = "gemini-3.5-flash-lite"
    # A title is a one-line task: low thinking saves tokens and latency
    title_thinking_level: Literal["minimal", "low", "medium", "high"] | None = "low"
    timeout_s: float = 120
    # Stream the main model's reasoning summaries as thought chunks (shown with /thoughts in the CLI)
    include_thoughts: bool = True


class BaseLLMConfigService(ABC):
    @property
    @abstractmethod
    def llm(self) -> LLMConfigModel:
        ...

    @property
    @abstractmethod
    def google_api_key(self) -> SecretStr:
        ...
