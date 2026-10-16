from collections.abc import AsyncGenerator

from httpx import AsyncClient, Timeout

from src.core.observability.tracing import trace_headers
from src.gateway.agent_api.config import BaseAgentAPIConfigService
from src.gateway.agent_api.dtos import PostAgentChatRequestDTO


class AgentAPIClient:
    def __init__(self, agent_api_config_service: BaseAgentAPIConfigService) -> None:
        config = agent_api_config_service.agent_api
        self._client = AsyncClient(
            base_url=config.base_url,
            timeout=Timeout(config.timeout or 180.0, connect=5.0)
        )

    async def stream_chat(self, user_id: str, dto: PostAgentChatRequestDTO) -> AsyncGenerator[str, None]:
        """Yields the agent's NDJSON lines. Raises ``httpx.HTTPError`` if the agent is unreachable or fails."""
        async with self._client.stream(
            "POST",
            "/chat/stream",
            json=dto.dto_dump(),
            headers={"X-User-Id": user_id, **trace_headers()}
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip():
                    yield line

    async def close(self) -> None:
        await self._client.aclose()
