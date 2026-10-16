from abc import ABC, abstractmethod

from pydantic import BaseModel

GIB = 1024**3


class BigQueryConfigModel(BaseModel):
    # Own GCP project: queries run (and are billed) here. The dataset itself is public.
    project_id: str | None = None
    dataset: str = "bigquery-public-data.thelook_ecommerce"
    location: str = "US"
    # Per-query guardrails
    max_bytes_billed: int = 1 * GIB
    max_rows: int = 1000
    query_timeout_s: float = 60
    max_transient_retries: int = 2


class BaseBigQueryConfigService(ABC):
    @property
    @abstractmethod
    def bigquery(self) -> BigQueryConfigModel:
        ...
