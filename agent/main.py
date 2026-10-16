from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.agent.context import add_identity_headers
from src.agent.graph import AgentGraphFactory
from src.agent.titles import ConversationTitleService
from src.backend_api.mcp import BackendMCPService
from src.chat.routers import router as chat_router
from src.chat.service import ChatService
from src.config.service import ConfigService
from src.core.fastapi.errors import register_unhandled_error_handler
from src.core.fastapi.health import HealthChecks, create_health_router
from src.core.observability.tracing import instrument_app
from src.llm.enums import LLMType
from src.llm.factory import LLMFactory

config_service = ConfigService()
health_checks = HealthChecks()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # startup
    backend_mcp_svc = BackendMCPService(config_service, tool_interceptors=[add_identity_headers])
    # Ready once the backend's tool list has loaded (it is cached after the first success)
    health_checks.add("backend_tools", backend_mcp_svc.get_tools)

    llm_factory = LLMFactory(config_service)
    graph_factory = AgentGraphFactory(llm_factory, backend_mcp_svc, config_service)
    chat_svc = ChatService(graph_factory, ConversationTitleService(llm_factory.get_llm(LLMType.TITLE)))
    app.dependency_overrides[ChatService] = lambda: chat_svc

    yield

    # shutdown


app = FastAPI(
    title="OpsFleet Data Agent API",
    lifespan=lifespan
)

register_unhandled_error_handler(app)
instrument_app(app)

app.include_router(create_health_router(health_checks))
app.include_router(chat_router, prefix="/api/agent")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app=app,
        host="0.0.0.0",
        port=config_service.config.agent_port
    )
