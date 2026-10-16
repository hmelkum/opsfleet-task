from src.artifacts.config import ArtifactsConfigModel
from src.core.api.config import APIConfigModel
from src.core.config.models import BaseConfigModel
from src.core.observability.config import TracingConfigModel
from src.core.postgres.config import PostgresDBConfigModel
from src.ecommerce.bigquery.config import BigQueryConfigModel


class ConfigModel(BaseConfigModel):
    backend_port: int
    postgres: PostgresDBConfigModel
    agent_api: APIConfigModel
    bigquery: BigQueryConfigModel
    artifacts: ArtifactsConfigModel = ArtifactsConfigModel()
    tracing: TracingConfigModel = TracingConfigModel()
