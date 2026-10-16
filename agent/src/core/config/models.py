from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.config.enums import EnvType


class BaseConfigModel(BaseSettings):
    model_config = SettingsConfigDict(
        frozen=True,
        env_parse_enums=True,
        env_nested_delimiter="__",
    )
    env: EnvType