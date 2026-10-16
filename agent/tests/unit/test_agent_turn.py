"""Whole turns through the real graph and middleware, with a scripted model, fake tools and a fake backend."""
import asyncio
import re
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
from google.genai import errors as genai_errors
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from opentelemetry import trace

from src.agent.config import AgentConfigModel
from src.agent.graph import AgentGraphFactory
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.tools import get_current_date
from src.chat.dtos import PostChatRequestDTO
from src.chat.service import (
    FAILURE_MESSAGE,
    STEP_LIMIT_MESSAGE,
    UNAVAILABLE_MESSAGE,
    ChatService,
)
from src.llm.enums import LLMType


class ScriptedModel(BaseChatModel):
    """Returns the scripted messages in order; an Exception in the script is raised."""
    script: list[Any]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        item = self.script[self.calls]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return ChatResult(generations=[ChatGeneration(message=item)])


def call(name: str, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": str(uuid4())}])


def structured(result: dict):
    return str(result), {"structured_content": {"result": result}}


def make_tools(seen: dict, sql_error: Exception | None = None, proposal: dict | None = None):
    def execute_sql_query(query: str):
        seen.setdefault("queries", []).append(query)
        if sql_error:
            raise sql_error
        return structured({"success": True, "columns": ["n"], "rows": [{"n": 42}], "truncated": False})

    def propose_reports_deletion(text: str | None = None):
        return structured(proposal or {"success": True, "proposal_id": None, "expires_at": None, "reports": []})

    return [
        StructuredTool.from_function(execute_sql_query, name="execute_sql_query", description="sql", response_format="content_and_artifact"),
        StructuredTool.from_function(propose_reports_deletion, name="propose_reports_deletion", description="delete", response_format="content_and_artifact"),
    ]


class FakeTitleService:
    def __init__(self, title=None):
        self.title = title
        self.calls = []

    async def generate(self, message, **event_ids):
        self.calls.append(message)
        return self.title


def make_service(script, fallback_script=(), tools=None, config=None, tools_error=None, title_svc=None):
    main, fallback = ScriptedModel(script=list(script)), ScriptedModel(script=list(fallback_script))

    async def get_tools():
        if tools_error:
            raise tools_error
        return tools if tools is not None else make_tools({})

    factory = AgentGraphFactory(
        SimpleNamespace(get_llm=lambda llm_type: {LLMType.MAIN: main, LLMType.FALLBACK: fallback}[llm_type]),
        SimpleNamespace(get_tools=get_tools),
        SimpleNamespace(agent=config or AgentConfigModel(model_retries=0))
    )
    return ChatService(factory, title_svc or FakeTitleService()), main, fallback


def run(svc, **dto) -> list[tuple[str, Any]]:
    async def _run():
        request = PostChatRequestDTO(conversation_id=uuid4(), turn_id=uuid4(), **dto)
        return [(c.type.value, c.content) async for c in svc.stream("user_alice", request)]

    return asyncio.run(_run())


def test_answer_and_sql_are_streamed():
    seen = {}
    svc, _, _ = make_service(
        [call("execute_sql_query", query="SELECT COUNT(*) AS n FROM orders"), AIMessage(content="There are 42 orders.")],
        tools=make_tools(seen),
    )
    chunks = run(svc, message="How many orders?")
    assert chunks == [
        ("tool_call", {"name": "execute_sql_query", "args": {"query": "SELECT COUNT(*) AS n FROM orders"}}),
        ("answer", "There are 42 orders."),
    ]
    assert seen["queries"] == ["SELECT COUNT(*) AS n FROM orders"]


def test_history_reaches_the_model():
    svc, main, _ = make_service([AIMessage(content="ok")])
    run(svc, message="and by month?", history=[{"role": "user", "content": "revenue?"}, {"role": "assistant", "content": "10k"}])
    assert main.calls == 1


def test_proposal_triggers_confirmation_required():
    proposal = {
        "success": True,
        "proposal_id": "11111111-1111-1111-1111-111111111111",
        "expires_at": "2026-10-15T19:00:00Z",
        "reports": [{"id": "r1", "title": "Calvin Klein Q1", "owner_id": "user_alice", "created_at": "2026-10-15T18:00:00Z"}],
    }
    svc, _, _ = make_service(
        [call("propose_reports_deletion", text="calvin"), AIMessage(content="This would delete 1 report. Please confirm.")],
        tools=make_tools({}, proposal=proposal),
    )
    chunks = run(svc, message="delete reports about calvin")
    assert chunks[0][0] == "tool_call" and chunks[0][1]["name"] == "propose_reports_deletion"
    assert chunks[1] == ("answer", "This would delete 1 report. Please confirm.")
    assert chunks[2] == ("confirmation_required", {
        "proposalId": proposal["proposal_id"],
        "expiresAt": proposal["expires_at"],
        "reports": [{"id": "r1", "title": "Calvin Klein Q1", "ownerId": "user_alice", "createdAt": "2026-10-15T18:00:00Z"}],
    })


def test_no_match_proposal_does_not_ask_for_confirmation():
    svc, _, _ = make_service([call("propose_reports_deletion", text="nothing"), AIMessage(content="Nothing matches.")])
    assert run(svc, message="delete reports about nothing") == [
        ("tool_call", {"name": "propose_reports_deletion", "args": {"text": "nothing"}}),
        ("answer", "Nothing matches."),
    ]


def test_the_agent_has_no_deletion_execution_path():
    """Execute and cancel live in the gateway. The agent only proposes, so its graph has no such node."""
    svc, _, _ = make_service([])
    graph = asyncio.run(svc._graph_factory.get_graph())
    assert {"agent", "request_confirmation"} <= set(graph.nodes)
    assert not any("deletion" in node or "decide" in node for node in graph.nodes)


def api_error(code: int) -> Exception:
    cls = genai_errors.ServerError if code >= 500 else genai_errors.ClientError
    return cls(code, {"error": {"code": code, "message": "x", "status": "X"}})


def test_model_failure_falls_back():
    svc, main, fallback = make_service(
        [api_error(429)],
        fallback_script=[AIMessage(content="answer from fallback")],
    )
    assert run(svc, message="hi") == [("answer", "answer from fallback")]
    assert main.calls == 1 and fallback.calls == 1


def test_model_retries_before_falling_back():
    svc, main, fallback = make_service(
        [api_error(503), AIMessage(content="second try")],
        config=AgentConfigModel(model_retries=1),
    )
    assert run(svc, message="hi") == [("answer", "second try")]
    assert main.calls == 2 and fallback.calls == 0


def test_billing_error_is_not_retried_but_falls_back():
    svc, main, fallback = make_service(
        [api_error(402)],
        fallback_script=[api_error(402)],
        config=AgentConfigModel(model_retries=2),
    )
    assert run(svc, message="hi") == [("error", FAILURE_MESSAGE)]
    assert main.calls == 1 and fallback.calls == 1


def test_all_models_failing_ends_with_safe_error():
    svc, _, _ = make_service([RuntimeError("boom")], fallback_script=[RuntimeError("boom again")])
    assert run(svc, message="hi") == [("error", FAILURE_MESSAGE)]


def test_step_limit_ends_with_safe_error():
    looping = [call("execute_sql_query", query=f"SELECT {i}") for i in range(10)]
    svc, _, _ = make_service(looping, config=AgentConfigModel(max_model_calls=3, max_tool_calls=10, model_retries=0))
    chunks = run(svc, message="loop forever")
    assert chunks[-1] == ("error", STEP_LIMIT_MESSAGE)
    assert [c[1]["args"]["query"] for c in chunks if c[0] == "tool_call"] == ["SELECT 0", "SELECT 1", "SELECT 2"]


def test_tool_budget_blocks_extra_calls():
    seen = {}
    script = [call("execute_sql_query", query=f"SELECT {i}") for i in range(3)] + [AIMessage(content="best effort answer")]
    svc, _, _ = make_service(script, tools=make_tools(seen), config=AgentConfigModel(max_tool_calls=2, model_retries=0))
    chunks = run(svc, message="many queries")
    assert seen["queries"] == ["SELECT 0", "SELECT 1"]
    assert chunks[-1] == ("answer", "best effort answer")


def test_tool_budget_counts_parallel_calls_in_one_model_turn():
    seen = {}
    parallel = AIMessage(content="", tool_calls=[
        {"name": "execute_sql_query", "args": {"query": f"SELECT {i}"}, "id": str(uuid4())} for i in range(3)
    ])
    svc, _, _ = make_service(
        [parallel, AIMessage(content="best effort answer")],
        tools=make_tools(seen),
        config=AgentConfigModel(max_tool_calls=2, model_retries=0),
    )
    chunks = run(svc, message="many queries at once")
    assert seen["queries"] == ["SELECT 0", "SELECT 1"]
    assert chunks[-1] == ("answer", "best effort answer")


def test_tool_exception_is_returned_to_the_model():
    svc, main, _ = make_service(
        [call("execute_sql_query", query="SELECT 1"), AIMessage(content="The data service is down, try later.")],
        tools=make_tools({}, sql_error=httpx.ConnectError("backend down")),
    )
    assert run(svc, message="q")[-1] == ("answer", "The data service is down, try later.")
    assert main.calls == 2


def test_backend_tools_unavailable():
    svc, _, _ = make_service([], tools_error=httpx.ConnectError("refused"))
    assert run(svc, message="hi") == [("error", UNAVAILABLE_MESSAGE)]


def test_turn_is_traced_with_correlated_events(spans):
    svc, _, _ = make_service(
        [call("execute_sql_query", query="SELECT 1"), AIMessage(content="done", usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13})],
    )
    turn_id, conversation_id = uuid4(), uuid4()

    async def _run():
        request = PostChatRequestDTO(conversation_id=conversation_id, turn_id=turn_id, message="q")
        with trace.get_tracer("test").start_as_current_span("request"):  # FastAPI opens this span in the service
            return [c async for c in svc.stream("user_alice", request)]

    asyncio.run(_run())
    finished = spans.get_finished_spans()
    assert {"request", "llm_call", "tool execute_sql_query"} <= {s.name for s in finished}
    events = [(e.name, dict(e.attributes)) for s in finished for e in s.events]
    assert {name for name, _ in events} == {"llm_call", "tool_call", "agent_turn"}
    assert all(a["turn_id"] == str(turn_id) and a["conversation_id"] == str(conversation_id) for _, a in events)
    turn = next(a for name, a in events if name == "agent_turn")
    assert turn["outcome"] == "answered" and turn["model_calls"] == 2 and turn["sql_queries"] == 1
    assert turn["output_tokens"] == 3
    assert [a["tool"] for name, a in events if name == "tool_call"] == ["execute_sql_query"]


def test_mcp_calls_carry_identity_and_trace_context(spans):
    from src.agent.context import AgentContext, add_identity_headers
    from langchain_mcp_adapters.interceptors import MCPToolCallRequest

    seen = {}

    async def handler(request):
        seen.update(request.headers)

    context = AgentContext(user_id="user_alice", conversation_id=uuid4(), turn_id=uuid4())
    request = MCPToolCallRequest(name="get_db_schema", args={}, server_name="ecommerce", runtime=SimpleNamespace(context=context))

    async def _run():
        with trace.get_tracer("test").start_as_current_span("tool get_db_schema") as span:
            await add_identity_headers(request, handler)
            return format(span.get_span_context().trace_id, "032x")

    trace_id = asyncio.run(_run())
    assert seen["X-User-Id"] == "user_alice" and seen["X-Conversation-Id"] == str(context.conversation_id)
    assert trace_id in seen["traceparent"]


def test_system_prompt_is_static_and_date_comes_from_a_tool():
    assert "{today}" not in SYSTEM_PROMPT
    assert "get_current_date" in SYSTEM_PROMPT
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \((Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\)", get_current_date.invoke({}))


def test_first_turn_gets_a_title_after_the_answer():
    titles = FakeTitleService("Order volume last month")
    svc, _, _ = make_service([AIMessage(content="42 orders.")], title_svc=titles)
    assert run(svc, message="How many orders last month?") == [
        ("answer", "42 orders."),
        ("title", "Order volume last month"),
    ]
    assert titles.calls == ["How many orders last month?"]


def test_reasoning_is_streamed_as_thought_before_the_answer():
    reasoning = AIMessage(content=[
        {"type": "reasoning", "reasoning": "Adding 12, 7 and 30 gives 49."},
        {"type": "text", "text": "44.1"},
    ])
    svc, _, _ = make_service([reasoning])
    assert run(svc, message="total after a 10% discount?") == [
        ("thought", "Adding 12, 7 and 30 gives 49."),
        ("answer", "44.1"),
    ]


def test_later_turns_get_no_title():
    titles = FakeTitleService("never")
    svc, _, _ = make_service([AIMessage(content="ok")], title_svc=titles)
    run(svc, message="and by month?", history=[{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}])
    assert titles.calls == []


def test_title_failure_does_not_affect_the_answer():
    from src.agent.titles import ConversationTitleService

    class FailingLLM:
        def with_structured_output(self, schema):
            return self

        async def ainvoke(self, prompt):
            raise RuntimeError("title model down")

    svc, _, _ = make_service([AIMessage(content="fine")], title_svc=ConversationTitleService(FailingLLM()))
    assert run(svc, message="q") == [("answer", "fine")]


def test_title_is_cleaned_and_bounded():
    from src.agent.titles import ConversationTitleOutput, ConversationTitleService

    class LLM:
        def with_structured_output(self, schema):
            assert "conversation_title" in schema.model_json_schema()["properties"]
            return self

        async def ainvoke(self, prompt):
            return ConversationTitleOutput(conversation_title='  "Q3   revenue by category."  ')

    assert asyncio.run(ConversationTitleService(LLM()).generate("q")) == "Q3 revenue by category"
