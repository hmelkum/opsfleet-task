from pydantic import SecretStr

from src.agent.config import AgentConfigModel
from src.core.api.config import APIConfigModel
from src.core.config.models import BaseConfigModel
from src.core.observability.config import TracingConfigModel
from src.llm.config import LLMConfigModel


class ConfigModel(BaseConfigModel):
    agent_port: int
    google_api_key: SecretStr
    llm: LLMConfigModel = LLMConfigModel()
    agent: AgentConfigModel = AgentConfigModel()
    tracing: TracingConfigModel = TracingConfigModel()
    ecommerce_mcp: APIConfigModel
    artifacts_mcp: APIConfigModel
