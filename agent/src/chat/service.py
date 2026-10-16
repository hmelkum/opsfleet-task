"""
Runs one turn of the agent graph and turns it into the NDJSON chunk stream.

Answer text comes from the model's token stream; ``tool_call`` and
``confirmation_required`` come from the graph's
custom stream. Every failure ends the stream with one safe ``error`` chunk:
technical details go to the log, never to the user.
"""
import asyncio
import logging
import time
from collections.abc import AsyncGenerator

from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from src.agent.context import AgentContext
from src.agent.graph import AgentGraphFactory
from src.agent.titles import ConversationTitleService
from src.chat.dtos import PostChatRequestDTO
from src.chat.models import ChatChunkModel, ChatChunkType, MessageRole
from src.core.fastapi.dependencies.wrappers import InjectPlaceholder
from src.core.observability.events import emit

logger = logging.getLogger(__name__)

UNAVAILABLE_MESSAGE = "The assistant is temporarily unavailable. Please try again in a moment."
STEP_LIMIT_MESSAGE = (
    "I couldn't finish this analysis within the allowed number of steps. "
    "Try a narrower question, or split it into smaller ones."
)
FAILURE_MESSAGE = "Something went wrong while answering. Please try again."

# The create_agent node whose tokens are the assistant's answer
_MODEL_NODE = "model"

# How long the end of a first turn waits for a still-running title call
_TITLE_TIMEOUT_S = 10


class ChatService:
    def __init__(
        self,
        graph_factory: AgentGraphFactory = InjectPlaceholder(),
        title_svc: ConversationTitleService = InjectPlaceholder()
    ) -> None:
        self._graph_factory = graph_factory
        self._title_svc = title_svc

    async def stream(self, user_id: str, dto: PostChatRequestDTO) -> AsyncGenerator[ChatChunkModel, None]:
        started = time.monotonic()
        context = AgentContext(user_id=user_id, conversation_id=dto.conversation_id, turn_id=dto.turn_id)
        outcome = "answered"
        confirmation_required = False
        # A conversation's first message also gets a title, generated alongside the answer.
        title_task = (
            asyncio.create_task(self._title_svc.generate(dto.message, **context.event_ids()))
            if dto.message is not None and not dto.history
            else None
        )
        try:
            async for chunk in self._run(context, dto):
                if chunk.type == ChatChunkType.CONFIRMATION_REQUIRED:
                    confirmation_required = True
                elif chunk.type == ChatChunkType.ERROR:
                    outcome = {
                        UNAVAILABLE_MESSAGE: "unavailable",
                        STEP_LIMIT_MESSAGE: "step_limit",
                    }.get(chunk.content, "failed")
                yield chunk

            if title_task is not None:
                try:
                    title = await asyncio.wait_for(title_task, _TITLE_TIMEOUT_S)
                except asyncio.TimeoutError:
                    title = None
                if title:
                    yield ChatChunkModel(type=ChatChunkType.TITLE, content=title)
        finally:
            if title_task is not None and not title_task.done():
                title_task.cancel()
            stats = context.stats
            emit(
                "agent_turn",
                **context.event_ids(),
                outcome=outcome,
                confirmation_required=confirmation_required,
                duration_ms=int((time.monotonic() - started) * 1000),
                history_messages=len(dto.history),
                model_calls=stats.model_calls,
                tool_calls=stats.tool_calls,
                sql_queries=stats.sql_queries,
                input_tokens=stats.input_tokens,
                output_tokens=stats.output_tokens,
                models=stats.models,
            )

    async def _run(self, context: AgentContext, dto: PostChatRequestDTO) -> AsyncGenerator[ChatChunkModel, None]:
        try:
            graph = await self._graph_factory.get_graph()
        except Exception:
            logger.exception("agent_graph_unavailable conversation_id=%s", dto.conversation_id)
            yield ChatChunkModel(type=ChatChunkType.ERROR, content=UNAVAILABLE_MESSAGE)
            return

        state = {"messages": self._to_messages(dto)}
        try:
            async for _, mode, data in graph.astream(
                state,
                context=context,
                stream_mode=["messages", "custom"],
                subgraphs=True
            ):
                if mode == "custom":
                    yield ChatChunkModel.model_validate(data)
                    continue

                chunk, metadata = data
                if metadata.get("langgraph_node") != _MODEL_NODE or not isinstance(chunk, AIMessage):
                    continue
                # token chunks, or whole messages from non-streaming models
                for block in chunk.content_blocks:
                    if block.get("type") == "reasoning" and block.get("reasoning"):
                        yield ChatChunkModel(type=ChatChunkType.THOUGHT, content=block["reasoning"])
                if chunk.text:
                    yield ChatChunkModel(type=ChatChunkType.ANSWER, content=chunk.text)
        except ModelCallLimitExceededError:
            logger.warning("agent_step_limit conversation_id=%s", dto.conversation_id)
            yield ChatChunkModel(type=ChatChunkType.ERROR, content=STEP_LIMIT_MESSAGE)
        except Exception:
            logger.exception("agent_turn_failed conversation_id=%s", dto.conversation_id)
            yield ChatChunkModel(type=ChatChunkType.ERROR, content=FAILURE_MESSAGE)

    @staticmethod
    def _to_messages(dto: PostChatRequestDTO) -> list[AnyMessage]:
        messages: list[AnyMessage] = [
            HumanMessage(content=message.content)
            if message.role == MessageRole.USER
            else AIMessage(content=message.content)
            for message in dto.history
        ]
        if dto.message is not None:
            messages.append(HumanMessage(content=dto.message))
        return messages
