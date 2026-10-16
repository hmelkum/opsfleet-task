import logging

from src.artifacts.config import ArtifactsConfigModel, BaseArtifactsConfigService
from src.config.model import ConfigModel
from src.core.api.config import APIConfigModel
from src.core.config.services import BaseConfigService
from src.core.observability.config import BaseTracingConfigService, TracingConfigModel
from src.core.observability.tracing import setup_tracing
from src.core.postgres.config import BasePostgresDBConfigService, PostgresDBConfigModel
from src.ecommerce.bigquery.config import BaseBigQueryConfigService, BigQueryConfigModel
from src.gateway.agent_api.config import BaseAgentAPIConfigService


class ConfigService(
    BaseConfigService[ConfigModel],
    BasePostgresDBConfigService,
    BaseAgentAPIConfigService,
    BaseBigQueryConfigService,
    BaseArtifactsConfigService,
    BaseTracingConfigService
):
    def __init__(self) -> None:
        super().__init__(ConfigModel)

        logging.basicConfig(format="%(levelname)-9s %(message)s", level=logging.INFO)
        setup_tracing("backend", self.config.tracing.otlp_endpoint)

    @property
    def postgres(self) -> PostgresDBConfigModel:
        return self.config.postgres

    @property
    def agent_api(self) -> APIConfigModel:
        return self.config.agent_api

    @property
    def bigquery(self) -> BigQueryConfigModel:
        return self.config.bigquery

    @property
    def artifacts(self) -> ArtifactsConfigModel:
        return self.config.artifacts

    @property
    def tracing(self) -> TracingConfigModel:
        return self.config.tracing
