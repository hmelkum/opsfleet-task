"""
The turn graph.

    START --> agent --> request_confirmation --> END

``agent`` is a ``create_agent`` ReAct loop over the backend's MCP tools, with
middleware for per-turn budgets, retries and a fallback model. The model can
only *propose* a deletion. ``request_confirmation`` is deterministic code that
tells the client a proposal is waiting. Executing or cancelling it is the
gateway's job, after the user answered the CLI's structured confirmation, so
this service holds no write path to the report library.
"""
import asyncio
from typing import Annotated, Any, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolErrorMiddleware,
)
from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph

from src.agent.config import BaseAgentConfigService
from src.agent.context import AgentContext
from src.agent.middleware import (
    is_transient_model_error,
    log_model_calls,
    log_tool_calls,
    on_tool_error,
    stream_tool_calls,
)
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.tools import get_current_date
from src.backend_api.mcp import BackendMCPService
from src.chat.models import ChatChunkModel, ChatChunkType
from src.llm.enums import LLMType
from src.llm.factory import LLMFactory

PROPOSE_DELETION_TOOL = "propose_reports_deletion"


class TurnState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class AgentGraphFactory:
    def __init__(
        self,
        llm_factory: LLMFactory,
        backend_mcp_svc: BackendMCPService,
        agent_config_service: BaseAgentConfigService
    ) -> None:
        self._llm_factory = llm_factory
        self._backend_mcp_svc = backend_mcp_svc
        self._config = agent_config_service.agent
        self._graph: CompiledStateGraph | None = None
        self._lock = asyncio.Lock()

    async def get_graph(self) -> CompiledStateGraph:
        """Built once, on first use: it needs the backend's tool list."""
        if self._graph is None:
            async with self._lock:
                if self._graph is None:
                    self._graph = self._build(await self._backend_mcp_svc.get_tools())
        return self._graph

    def _build(self, tools: list) -> CompiledStateGraph:
        # The system prompt is static so its prefix stays cacheable; dynamic facts (today's date) come from tools.
        agent = create_agent(
            model=self._llm_factory.get_llm(LLMType.MAIN),
            tools=[*tools, get_current_date],
            system_prompt=SYSTEM_PROMPT,
            context_schema=AgentContext,
            middleware=[
                ModelCallLimitMiddleware(run_limit=self._config.max_model_calls, exit_behavior="error"),
                ToolCallLimitMiddleware(run_limit=self._config.max_tool_calls),
                # Fallback wraps retry: the main model is retried first, then the fallback model.
                ModelFallbackMiddleware(self._llm_factory.get_llm(LLMType.FALLBACK)),
                ModelRetryMiddleware(
                    max_retries=self._config.model_retries,
                    retry_on=is_transient_model_error,
                    on_failure="error"
                ),
                log_model_calls,  # innermost model wrapper: logs every actual attempt
                stream_tool_calls,
                log_tool_calls,
                ToolErrorMiddleware(on_tool_error),
            ]
        )

        builder = StateGraph(TurnState, context_schema=AgentContext)
        builder.add_node("agent", agent)
        builder.add_node("request_confirmation", self._request_confirmation)
        builder.add_edge(START, "agent")
        builder.add_edge("agent", "request_confirmation")
        builder.add_edge("request_confirmation", END)
        return builder.compile()

    @staticmethod
    def _request_confirmation(state: TurnState) -> dict[str, Any]:
        """If this turn proposed a deletion, asks the client for a structured confirmation."""
        for message in reversed(state["messages"]):
            if isinstance(message, HumanMessage):
                break
            if isinstance(message, ToolMessage) and message.name == PROPOSE_DELETION_TOOL:
                result = ((message.artifact or {}).get("structured_content") or {}).get("result") or {}
                if result.get("proposal_id"):
                    get_stream_writer()(
                        ChatChunkModel(
                            type=ChatChunkType.CONFIRMATION_REQUIRED,
                            content={
                                "proposalId": result["proposal_id"],
                                "expiresAt": result["expires_at"],
                                "reports": [
                                    {
                                        "id": report["id"],
                                        "title": report["title"],
                                        "ownerId": report["owner_id"],
                                        "createdAt": report["created_at"],
                                    }
                                    for report in result["reports"]
                                ],
                            }
                        ).model_dump()
                    )
                break
        return {}
