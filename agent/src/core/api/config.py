from pydantic import BaseModel


class APIConfigModel(BaseModel):
    scheme: str
    hostname: str
    port: int | None = None
    endpoint: str | None = None
    version: str | None = None
    timeout: float | None = None

    @property
    def base_url(self) -> str:
        url = f"{self.scheme}://{self.hostname}"
        url = f"{url}:{self.port}" if self.port else url
        return f"{url}/{self.endpoint}" if self.endpoint else url
