from abc import ABC, abstractmethod

from src.core.api.config import APIConfigModel


class BaseAgentAPIConfigService(ABC):
    @property
    @abstractmethod
    def agent_api(self) -> APIConfigModel:
        ...
