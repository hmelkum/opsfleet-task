import asyncio
from collections.abc import Sequence

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import ToolCallInterceptor

from src.backend_api.config import BaseBackendAPIConfigService


class BackendMCPService:
    """The backend's MCP servers, registered by URL so a module can move to its own service by config.

    Tools are loaded once and shared by every request. Each call opens its own session, so the
    interceptors can set per-request headers (identity) without any shared state.
    """

    def __init__(
        self,
        backend_api_config_service: BaseBackendAPIConfigService,
        tool_interceptors: Sequence[ToolCallInterceptor]
    ) -> None:
        self._client = MultiServerMCPClient(
            {
                "ecommerce": {
                    "transport": "streamable_http",
                    "url": backend_api_config_service.ecommerce_mcp.base_url
                },
                "artifacts": {
                    "transport": "streamable_http",
                    "url": backend_api_config_service.artifacts_mcp.base_url
                },
            },
            tool_interceptors=list(tool_interceptors)
        )
        self._tools: list[BaseTool] | None = None
        self._lock = asyncio.Lock()

    async def get_tools(self) -> list[BaseTool]:
        """Loaded on first use, so the agent starts even if the backend is not up yet."""
        if self._tools is None:
            async with self._lock:
                if self._tools is None:
                    self._tools = await self._client.get_tools()
        return self._tools
