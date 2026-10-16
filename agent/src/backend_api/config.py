from abc import ABC, abstractmethod

from src.core.api.config import APIConfigModel


class BaseBackendAPIConfigService(ABC):
    @property
    @abstractmethod
    def ecommerce_mcp(self) -> APIConfigModel:
        ...

    @property
    @abstractmethod
    def artifacts_mcp(self) -> APIConfigModel:
        ...
