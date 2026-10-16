from abc import ABC, abstractmethod

from pydantic import BaseModel, SecretStr
from sqlalchemy.engine import URL


class PostgresDBConfigModel(BaseModel):
    host: str
    port: int
    username: str
    password: SecretStr
    database: str

    @property
    def url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.username,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.database,
        )


class BasePostgresDBConfigService(ABC):
    @property
    @abstractmethod
    def postgres(self) -> PostgresDBConfigModel:
        ...