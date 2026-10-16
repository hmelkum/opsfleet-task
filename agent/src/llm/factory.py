from langchain_google_genai import ChatGoogleGenerativeAI

from src.llm.config import BaseLLMConfigService
from src.llm.enums import LLMType


class LLMFactory:
    def __init__(self, llm_config_service: BaseLLMConfigService) -> None:
        self._config_service = llm_config_service

    def get_llm(self, llm_type: LLMType) -> ChatGoogleGenerativeAI:
        match llm_type:
            case LLMType.MAIN:
                return self._get_google_llm(
                    self._config_service.llm.main_model,
                    include_thoughts=self._config_service.llm.include_thoughts
                )
            case LLMType.FALLBACK:
                return self._get_google_llm(self._config_service.llm.fallback_model)
            case LLMType.TITLE:
                return self._get_google_llm(
                    self._config_service.llm.title_model,
                    thinking_level=self._config_service.llm.title_thinking_level
                )

    def _get_google_llm(
        self,
        model: str,
        include_thoughts: bool = False,
        thinking_level: str | None = None
    ) -> ChatGoogleGenerativeAI:
        # Sampling parameters stay at the model defaults: Google recommends temperature 1.0 for Gemini 3.
        # The thinking level is the model default unless set (the title model uses a low one).
        # Retries are handled by the agent's middleware, so the client does not retry on its own.
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=self._config_service.google_api_key.get_secret_value(),
            include_thoughts=include_thoughts,
            thinking_level=thinking_level,
            max_retries=0,
            timeout=self._config_service.llm.timeout_s
        )
