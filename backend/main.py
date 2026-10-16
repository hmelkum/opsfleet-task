from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastmcp import FastMCP
from sqlalchemy import text

from src.artifacts.repositories.artifacts import ArtifactRepository
from src.artifacts.repositories.deletions import DeletionRepository
from src.artifacts.repositories.reports import ReportRepository
from src.artifacts.routers.artifacts import router as artifacts_router
from src.artifacts.services.artifacts import ArtifactService
from src.artifacts.services.deletions import DeletionService
from src.artifacts.services.reports import ReportService
from src.artifacts.tools.tools import ArtifactToolset
from src.config.service import ConfigService
from src.core.fastapi.errors import register_unhandled_error_handler
from src.core.fastapi.health import HealthChecks, create_health_router
from src.core.observability.middleware import (
    MCPTraceContextMiddleware,
    TraceContextMiddleware,
)
from src.core.observability.tracing import instrument_app
from src.core.postgres.context import PostgresDBContext
from src.ecommerce.bigquery.safe_runner import SafeBigQueryRunner
from src.ecommerce.sql.virtual_tables import VirtualTables
from src.ecommerce.tools.tools import EcommerceToolset
from src.gateway.agent_api.circuit_breaker import CircuitBreaker
from src.gateway.agent_api.client import AgentAPIClient
from src.gateway.repositories.conversations import ConversationRepository
from src.gateway.repositories.feedbacks import FeedbackRepository
from src.gateway.repositories.messages import MessageRepository
from src.gateway.routers.chat import router as chat_router
from src.gateway.routers.conversations import router as conversations_router
from src.gateway.routers.feedbacks import router as feedbacks_router
from src.gateway.services.chat import ChatService
from src.gateway.services.conversations import ConversationService
from src.gateway.services.feedbacks import FeedbackService

config_service = ConfigService()
health_checks = HealthChecks()

ecommerce_mcp = FastMCP("Ecommerce Tools")
ecommerce_mcp.add_middleware(MCPTraceContextMiddleware())
ecommerce_mcp_app = ecommerce_mcp.http_app(path="/mcp", stateless_http=True)

artifacts_mcp = FastMCP("Artifacts Tools")
artifacts_mcp.add_middleware(MCPTraceContextMiddleware())
artifacts_mcp_app = artifacts_mcp.http_app(path="/mcp", stateless_http=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(ecommerce_mcp_app.lifespan(ecommerce_mcp_app))
        await stack.enter_async_context(artifacts_mcp_app.lifespan(artifacts_mcp_app))

        # startup
        db_context = PostgresDBContext(config_service)

        async def postgres_ready() -> None:
            async with db_context.session() as session:
                await session.execute(text("SELECT 1"))

        health_checks.add("postgres", postgres_ready)
        agent_api_client = AgentAPIClient(config_service)

        # ecommerce
        ecommerce_toolset = EcommerceToolset(
            runner=SafeBigQueryRunner(config_service),
            virtual_tables=VirtualTables(config_service)
        )
        ecommerce_mcp.add_tool(ecommerce_toolset.get_db_schema)
        ecommerce_mcp.add_tool(ecommerce_toolset.execute_sql_query)

        # artifacts
        report_svc = ReportService(ReportRepository(db_context), config_service)
        deletion_svc = DeletionService(report_svc, DeletionRepository(db_context), config_service)
        artifact_svc = ArtifactService(ArtifactRepository(db_context), report_svc)
        app.dependency_overrides[ArtifactService] = lambda: artifact_svc

        artifact_toolset = ArtifactToolset(report_svc, deletion_svc)
        artifacts_mcp.add_tool(artifact_toolset.save_report)
        artifacts_mcp.add_tool(artifact_toolset.search_reports)
        artifacts_mcp.add_tool(artifact_toolset.get_report)
        artifacts_mcp.add_tool(artifact_toolset.propose_reports_deletion)

        # gateway
        conversation_repo = ConversationRepository(db_context)
        message_repo = MessageRepository(db_context)
        chat_svc = ChatService(
            conversation_repo,
            message_repo,
            agent_api_client,
            CircuitBreaker(failure_threshold=3, reset_timeout_s=30),
            deletion_svc
        )
        app.dependency_overrides[ChatService] = lambda: chat_svc

        conversation_svc = ConversationService(conversation_repo, message_repo)
        app.dependency_overrides[ConversationService] = lambda: conversation_svc

        feedback_svc = FeedbackService(conversation_repo, message_repo, FeedbackRepository(db_context))
        app.dependency_overrides[FeedbackService] = lambda: feedback_svc

        yield

        # shutdown
        await agent_api_client.close()
        await db_context.close()


app = FastAPI(
    title="OpsFleet Data Agent Backend API",
    lifespan=lifespan
)

app.add_middleware(TraceContextMiddleware)
register_unhandled_error_handler(app)
instrument_app(app)

app.mount("/mcp/ecommerce", ecommerce_mcp_app)
app.mount("/mcp/artifacts", artifacts_mcp_app)

app.include_router(create_health_router(health_checks))
app.include_router(chat_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(feedbacks_router, prefix="/api")
app.include_router(artifacts_router, prefix="/api")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app=app,
        host="0.0.0.0",
        port=config_service.config.backend_port
    )
