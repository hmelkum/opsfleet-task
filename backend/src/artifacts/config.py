from abc import ABC, abstractmethod

from pydantic import BaseModel


class ArtifactsConfigModel(BaseModel):
    deletion_proposal_ttl_s: int = 300
    max_search_results: int = 50


class BaseArtifactsConfigService(ABC):
    @property
    @abstractmethod
    def artifacts(self) -> ArtifactsConfigModel:
        ...
