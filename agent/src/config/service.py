import logging

from pydantic import SecretStr

from src.agent.config import AgentConfigModel, BaseAgentConfigService
from src.backend_api.config import BaseBackendAPIConfigService
from src.config.model import ConfigModel
from src.core.api.config import APIConfigModel
from src.core.config.services import BaseConfigService
from src.core.observability.config import BaseTracingConfigService, TracingConfigModel
from src.core.observability.tracing import setup_tracing
from src.llm.config import BaseLLMConfigService, LLMConfigModel


class ConfigService(
    BaseConfigService[ConfigModel],
    BaseLLMConfigService,
    BaseAgentConfigService,
    BaseBackendAPIConfigService,
    BaseTracingConfigService
):
    def __init__(self) -> None:
        super().__init__(ConfigModel)

        logging.basicConfig(format="%(levelname)-9s %(message)s", level=logging.INFO)
        setup_tracing("agent", self.config.tracing.otlp_endpoint)

    @property
    def llm(self) -> LLMConfigModel:
        return self.config.llm

    @property
    def google_api_key(self) -> SecretStr:
        return self.config.google_api_key

    @property
    def agent(self) -> AgentConfigModel:
        return self.config.agent

    @property
    def ecommerce_mcp(self) -> APIConfigModel:
        return self.config.ecommerce_mcp

    @property
    def artifacts_mcp(self) -> APIConfigModel:
        return self.config.artifacts_mcp

    @property
    def tracing(self) -> TracingConfigModel:
        return self.config.tracing
