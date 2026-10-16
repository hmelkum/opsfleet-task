from src.core.config.enums import EnvType
from src.core.config.models import BaseConfigModel


class BaseConfigService[T: BaseConfigModel]:
    def __init__(self, config_cls: type[T]) -> None:
        self._config = config_cls()

    @property
    def config(self) -> T:
        return self._config

    @property
    def env(self) -> EnvType:
        return self.config.env
 