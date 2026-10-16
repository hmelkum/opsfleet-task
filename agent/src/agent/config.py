from abc import ABC, abstractmethod

from pydantic import BaseModel


class AgentConfigModel(BaseModel):
    # Per-turn budgets: resilience and cost caps
    max_model_calls: int = 20
    # Counts every tool call, including several requested in one model turn
    max_tool_calls: int = 20
    model_retries: int = 2


class BaseAgentConfigService(ABC):
    @property
    @abstractmethod
    def agent(self) -> AgentConfigModel:
        ...
