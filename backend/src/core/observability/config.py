from abc import ABC, abstractmethod

from pydantic import BaseModel


class TracingConfigModel(BaseModel):
    # OTLP/HTTP collector base URL, e.g. http://localhost:4318 (Jaeger). Empty: spans are not exported.
    otlp_endpoint: str | None = None


class BaseTracingConfigService(ABC):
    @property
    @abstractmethod
    def tracing(self) -> TracingConfigModel:
        ...
