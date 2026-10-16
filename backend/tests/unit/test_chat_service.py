"""ChatService with in-memory repositories and a fake agent behind httpx.MockTransport."""
import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from src.core.api.config import APIConfigModel
from src.core.deletions.port import (
    DeletedReport,
    DeletionPort,
    DeletionProposalNotPendingError,
)
from src.core.identity.users import parse_user_id
from src.gateway.agent_api.circuit_breaker import CircuitBreaker, CircuitState
from src.gateway.agent_api.client import AgentAPIClient
from src.gateway.dtos.chat import PostChatRequestDTO
from src.gateway.exceptions import ConversationNotFoundError
from src.gateway.models.chat import ChatChunkType
from src.gateway.services.chat import (
    AGENT_UNAVAILABLE_MESSAGE,
    DELETION_DECLINED_MESSAGE,
    DELETION_HANDLED_MESSAGE,
    DELETION_UNAVAILABLE_MESSAGE,
    ChatService,
)

ALICE = parse_user_id("user_alice")
BOB = parse_user_id("user_bob")


class FakeConversationRepository:
    def __init__(self):
        self.items = {}

    async def add(self, conversation):
        self.items[conversation.id] = conversation
        return conversation

    async def get(self, conversation_id):
        return self.items.get(conversation_id)

    async def set_title(self, conversation_id, title):
        if self.items[conversation_id].title is None:
            self.items[conversation_id].title = title


class FakeMessageRepository:
    def __init__(self):
        self.items = []

    async def add(self, message):
        self.items.append(message)
        return message

    async def get_all(self, conversation_id):
        return [m for m in self.items if m.conversation_id == conversation_id]

    async def get_user_message(self, conversation_id, message_id):
        return next((m for m in self.items if m.id == message_id and m.conversation_id == conversation_id and m.role == "user"), None)


class FakeDeletionPort(DeletionPort):
    def __init__(self, deleted=(), error=None):
        self.deleted, self.error, self.calls = list(deleted), error, []

    async def execute(self, user, conversation_id, proposal_id):
        self.calls.append(("execute", proposal_id))
        if self.error:
            raise self.error
        return self.deleted

    async def cancel(self, user, conversation_id, proposal_id):
        self.calls.append(("cancel", proposal_id))
        if self.error:
            raise self.error


def make_service(handler, breaker=None, deletion_port=None):
    agent_client = AgentAPIClient(
        SimpleNamespace(agent_api=APIConfigModel(scheme="http", hostname="agent", port=8090, endpoint="api/agent"))
    )
    agent_client._client = httpx.AsyncClient(base_url="http://agent:8090/api/agent", transport=httpx.MockTransport(handler))
    messages = FakeMessageRepository()
    svc = ChatService(
        FakeConversationRepository(), messages, agent_client, breaker or CircuitBreaker(3, 30),
        deletion_port or FakeDeletionPort()
    )
    return svc, messages


def ndjson(*chunks) -> bytes:
    return "".join(json.dumps(c) + "\n" for c in chunks).encode()


LAST_TURN = {}


def run_turn(svc, user, dto):
    """Runs one turn; returns the conversation id and the chunks after the leading conversation chunk."""
    async def _run():
        conversation_id = await svc.open_conversation(user, dto.conversation_id)
        chunks = [chunk async for chunk in svc.stream(user, conversation_id, dto)]
        assert chunks[0].type == ChatChunkType.CONVERSATION
        assert chunks[0].content["conversationId"] == str(conversation_id)
        LAST_TURN["id"] = chunks[0].content["turnId"]
        return conversation_id, chunks[1:]

    return asyncio.run(_run())


def test_relays_agent_stream_and_records_transcript():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["user"] = request.headers["X-User-Id"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=ndjson(
            {"type": "tool_call", "content": {"name": "execute_sql_query", "args": {"query": "SELECT 1"}}},
            {"type": "answer", "content": "Revenue "},
            {"type": "answer", "content": "grew."},
        ))

    svc, messages = make_service(handler)
    conversation_id, chunks = run_turn(svc, ALICE, PostChatRequestDTO(message="How is revenue?"))

    assert [(c.type, c.content) for c in chunks] == [
        (ChatChunkType.TOOL_CALL, {"name": "execute_sql_query", "args": {"query": "SELECT 1"}}),
        (ChatChunkType.ANSWER, "Revenue grew."),
    ]
    assert seen["url"] == "http://agent:8090/api/agent/chat/stream"
    assert seen["user"] == "user_alice"
    assert seen["body"]["turnId"] == LAST_TURN["id"] == str(messages.items[0].id)  # the turn is the user's message
    assert seen["body"]["conversationId"] == str(conversation_id)
    assert seen["body"]["message"] == "How is revenue?" and seen["body"]["history"] == []
    assert [(m.role, m.content) for m in messages.items] == [("user", "How is revenue?"), ("assistant", "Revenue grew.")]


def test_full_history_is_sent_on_every_turn():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=ndjson({"type": "answer", "content": f"answer {len(bodies)}"}))

    svc, _ = make_service(handler)
    conversation_id, _ = run_turn(svc, ALICE, PostChatRequestDTO(message="first"))
    for i in range(2, 13):
        run_turn(svc, ALICE, PostChatRequestDTO(conversation_id=conversation_id, message=f"message {i}"))

    assert bodies[1]["history"] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer 1"},
    ]
    # the full transcript, never a sliding window, so the prompt prefix stays stable for caching
    assert len(bodies[-1]["history"]) == 22 and bodies[-1]["history"][:2] == bodies[1]["history"]


def test_agent_down_yields_safe_error_and_keeps_user_message():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    svc, messages = make_service(handler)
    _, chunks = run_turn(svc, ALICE, PostChatRequestDTO(message="hello"))

    assert [(c.type, c.content) for c in chunks] == [(ChatChunkType.ERROR, AGENT_UNAVAILABLE_MESSAGE)]
    assert [m.role for m in messages.items] == ["user"]


def test_agent_5xx_yields_safe_error():
    svc, _ = make_service(lambda request: httpx.Response(503, text="Service Unavailable"))
    _, chunks = run_turn(svc, ALICE, PostChatRequestDTO(message="hello"))
    assert [(c.type, c.content) for c in chunks] == [(ChatChunkType.ERROR, AGENT_UNAVAILABLE_MESSAGE)]


def test_malformed_agent_line_yields_safe_error_after_good_chunks():
    svc, messages = make_service(lambda request: httpx.Response(200, content=b'{"type":"answer","content":"partial"}\nnot json\n'))
    _, chunks = run_turn(svc, ALICE, PostChatRequestDTO(message="hello"))
    assert [c.type for c in chunks] == [ChatChunkType.ANSWER, ChatChunkType.ERROR]
    assert messages.items[-1].content == "partial"


def _proposal_turn(svc):
    """The first turn of a conversation, in which the agent proposed a deletion; returns the conversation id."""
    conversation_id, _ = run_turn(svc, ALICE, PostChatRequestDTO(message="delete calvin reports"))
    return conversation_id


def test_confirmed_deletion_runs_in_the_gateway_and_is_recorded():
    agent_requests = []

    def handler(request):
        agent_requests.append(request)
        return httpx.Response(200, content=ndjson({"type": "answer", "content": "This would delete 1 report."}))

    port = FakeDeletionPort(deleted=[DeletedReport(id=uuid4(), title="Calvin Klein Q1", owner_id="user_alice")])
    svc, messages = make_service(handler, deletion_port=port)
    conversation_id = _proposal_turn(svc)

    proposal_id = uuid4()
    _, chunks = run_turn(svc, ALICE, PostChatRequestDTO(
        conversation_id=conversation_id,
        confirmation={"proposal_id": proposal_id, "confirmed": True}
    ))

    assert len(agent_requests) == 1  # only the proposing turn reached the agent
    assert port.calls == [("execute", proposal_id)]
    assert [(c.type, c.content) for c in chunks] == [(ChatChunkType.ANSWER, "Deleted 1 report(s):\n- Calvin Klein Q1")]
    # the transcript keeps the decision and the outcome, so the next turn sees both
    assert [(m.role, m.content) for m in messages.items] == [
        ("user", "delete calvin reports"),
        ("assistant", "This would delete 1 report."),
        ("user", "Confirmed the deletion."),
        ("assistant", "Deleted 1 report(s):\n- Calvin Klein Q1"),
    ]


def test_declined_deletion_cancels_and_is_recorded():
    port = FakeDeletionPort()
    svc, messages = make_service(
        lambda request: httpx.Response(200, content=ndjson({"type": "answer", "content": "Will do."})),
        deletion_port=port,
    )
    conversation_id = _proposal_turn(svc)
    proposal_id = uuid4()
    _, chunks = run_turn(svc, ALICE, PostChatRequestDTO(
        conversation_id=conversation_id,
        confirmation={"proposal_id": proposal_id, "confirmed": False}
    ))
    assert port.calls == [("cancel", proposal_id)]
    assert [(c.type, c.content) for c in chunks] == [(ChatChunkType.ANSWER, DELETION_DECLINED_MESSAGE)]
    assert messages.items[-2].content == "Declined the deletion."
    assert messages.items[-1].content == DELETION_DECLINED_MESSAGE


def test_expired_proposal_deletes_nothing_and_says_so():
    svc, messages = make_service(
        lambda request: httpx.Response(200, content=ndjson({"type": "answer", "content": "ok"})),
        deletion_port=FakeDeletionPort(error=DeletionProposalNotPendingError("expired")),
    )
    conversation_id = _proposal_turn(svc)
    _, chunks = run_turn(svc, ALICE, PostChatRequestDTO(
        conversation_id=conversation_id,
        confirmation={"proposal_id": uuid4(), "confirmed": True}
    ))
    assert [(c.type, c.content) for c in chunks] == [(ChatChunkType.ANSWER, DELETION_HANDLED_MESSAGE)]
    assert messages.items[-1].content == DELETION_HANDLED_MESSAGE


def test_database_outage_during_deletion_is_a_safe_message():
    svc, messages = make_service(
        lambda request: httpx.Response(200, content=ndjson({"type": "answer", "content": "ok"})),
        deletion_port=FakeDeletionPort(error=SQLAlchemyError("connection refused")),
    )
    conversation_id = _proposal_turn(svc)
    _, chunks = run_turn(svc, ALICE, PostChatRequestDTO(
        conversation_id=conversation_id,
        confirmation={"proposal_id": uuid4(), "confirmed": True}
    ))
    assert [(c.type, c.content) for c in chunks] == [(ChatChunkType.ANSWER, DELETION_UNAVAILABLE_MESSAGE)]
    assert messages.items[-1].content == DELETION_UNAVAILABLE_MESSAGE


def test_deleted_titles_are_pii_masked_like_answers():
    port = FakeDeletionPort(deleted=[DeletedReport(id=uuid4(), title="Report for jane.doe@example.com", owner_id="user_alice")])
    svc, messages = make_service(
        lambda request: httpx.Response(200, content=ndjson({"type": "answer", "content": "ok"})),
        deletion_port=port,
    )
    conversation_id = _proposal_turn(svc)
    _, chunks = run_turn(svc, ALICE, PostChatRequestDTO(
        conversation_id=conversation_id,
        confirmation={"proposal_id": uuid4(), "confirmed": True}
    ))
    streamed = "".join(c.content for c in chunks)
    assert "jane.doe@example.com" not in streamed and "[email removed]" in streamed
    assert messages.items[-1].content == streamed


def test_thoughts_are_masked_across_chunks_and_never_stored():
    handler = lambda request: httpx.Response(200, content=ndjson(
        {"type": "thought", "content": "The question mentions jane.do"},
        {"type": "thought", "content": "e@example.com, so search by name."},
        {"type": "answer", "content": "Done."},
    ))
    svc, messages = make_service(handler)
    _, chunks = run_turn(svc, ALICE, PostChatRequestDTO(message="q"))
    thoughts = "".join(c.content for c in chunks if c.type == ChatChunkType.THOUGHT)
    assert "jane" not in thoughts and "example.com" not in thoughts and "[email removed]" in thoughts
    assert [c.type for c in chunks][:1] == [ChatChunkType.THOUGHT]
    assert [m.content for m in messages.items] == ["q", "Done."]


def test_other_users_conversation_is_not_found():
    svc, _ = make_service(lambda request: httpx.Response(200, content=b""))
    conversation_id, _ = run_turn(svc, ALICE, PostChatRequestDTO(message="hi"))
    with pytest.raises(ConversationNotFoundError):
        asyncio.run(svc.open_conversation(BOB, conversation_id))
    with pytest.raises(ConversationNotFoundError):
        asyncio.run(svc.open_conversation(ALICE, uuid4()))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": "   "},
        {"message": "hi", "confirmation": {"proposalId": str(uuid4()), "confirmed": True}},
        {"confirmation": {"proposalId": str(uuid4()), "confirmed": True}},  # no conversation id
    ],
)
def test_invalid_requests(payload):
    with pytest.raises(ValidationError):
        PostChatRequestDTO.model_validate(payload)


def test_request_accepts_camel_case():
    conversation_id = uuid4()
    dto = PostChatRequestDTO.model_validate({"conversationId": str(conversation_id), "message": "hi"})
    assert dto.conversation_id == conversation_id


def test_feedback_rates_own_turns_only():
    from src.gateway.exceptions import TurnNotFoundError
    from src.gateway.models.chat import FeedbackRating
    from src.gateway.services.feedbacks import FeedbackService

    class FakeFeedbackRepository:
        def __init__(self):
            self.items = {}

        async def upsert(self, feedback):
            self.items[feedback.turn_id] = feedback

    svc, messages = make_service(lambda request: httpx.Response(200, content=ndjson({"type": "answer", "content": "a"})))
    conversation_id, _ = run_turn(svc, ALICE, PostChatRequestDTO(message="q"))
    turn_id = messages.items[0].id
    feedbacks = FakeFeedbackRepository()
    feedback_svc = FeedbackService(svc._conversation_repo, messages, feedbacks)

    asyncio.run(feedback_svc.rate(ALICE, conversation_id, turn_id, FeedbackRating.UP, None))
    asyncio.run(feedback_svc.rate(ALICE, conversation_id, turn_id, FeedbackRating.DOWN, "too long"))
    assert feedbacks.items[turn_id].rating == "down" and feedbacks.items[turn_id].comment == "too long"

    with pytest.raises(ConversationNotFoundError):
        asyncio.run(feedback_svc.rate(BOB, conversation_id, turn_id, FeedbackRating.UP, None))
    with pytest.raises(TurnNotFoundError):  # the assistant message is not a turn id
        asyncio.run(feedback_svc.rate(ALICE, conversation_id, messages.items[1].id, FeedbackRating.UP, None))


def test_answer_is_pii_masked_before_client_and_transcript():
    long_tail = " Revenue grew in every region this quarter." * 4
    handler = lambda request: httpx.Response(200, content=ndjson(
        {"type": "answer", "content": "Contact jane.d"},
        {"type": "answer", "content": "oe@example.com or call +1 555 123 4567."},
        {"type": "answer", "content": long_tail},
        {"type": "tool_call", "content": {"name": "execute_sql_query", "args": {"query": "SELECT 1"}}},
        {"type": "answer", "content": " Done."},
    ))
    svc, messages = make_service(handler)
    _, chunks = run_turn(svc, ALICE, PostChatRequestDTO(message="q"))
    streamed = "".join(c.content for c in chunks if c.type == ChatChunkType.ANSWER)
    assert "jane" not in streamed and "555" not in streamed
    assert "[email removed]" in streamed and "[phone removed]" in streamed
    assert streamed.endswith("Done.") and messages.items[-1].content == streamed
    # answer text before the sql chunk is released before it
    types = [c.type for c in chunks]
    assert types.index(ChatChunkType.TOOL_CALL) > types.index(ChatChunkType.ANSWER)


def test_circuit_opens_after_repeated_agent_failures_and_recovers():
    now = {"t": 0.0}
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_s=30, clock=lambda: now["t"])
    calls = {"n": 0, "fail": True}

    def handler(request):
        calls["n"] += 1
        if calls["fail"]:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, content=ndjson({"type": "answer", "content": "back"}))

    svc, _ = make_service(handler, breaker)
    for _ in range(2):
        run_turn(svc, ALICE, PostChatRequestDTO(message="q"))
    assert breaker.state == CircuitState.OPEN and calls["n"] == 2

    _, chunks = run_turn(svc, ALICE, PostChatRequestDTO(message="q"))  # short-circuited
    assert calls["n"] == 2 and chunks[-1].type == ChatChunkType.ERROR

    now["t"] = 31.0  # half-open: one trial goes through
    calls["fail"] = False
    _, chunks = run_turn(svc, ALICE, PostChatRequestDTO(message="q"))
    assert calls["n"] == 3 and chunks[-1].content == "back"
    assert breaker.state == CircuitState.CLOSED


def test_failed_trial_reopens_the_circuit():
    now = {"t": 0.0}
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_s=30, clock=lambda: now["t"])
    svc, _ = make_service(lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused")), breaker)
    run_turn(svc, ALICE, PostChatRequestDTO(message="q"))
    now["t"] = 31.0
    run_turn(svc, ALICE, PostChatRequestDTO(message="q"))
    assert breaker.state == CircuitState.OPEN


def test_title_chunk_is_stored_and_not_forwarded():
    svc, _ = make_service(lambda request: httpx.Response(200, content=ndjson(
        {"type": "answer", "content": "Revenue grew."},
        {"type": "title", "content": "Revenue growth overview"},
    )))
    conversation_id, chunks = run_turn(svc, ALICE, PostChatRequestDTO(message="How is revenue?"))
    assert [c.type for c in chunks] == [ChatChunkType.ANSWER]
    assert svc._conversation_repo.items[conversation_id].title == "Revenue growth overview"


def test_conversation_list_falls_back_to_first_message():
    from datetime import UTC, datetime
    from types import SimpleNamespace as NS

    from src.gateway.services.conversations import ConversationService

    now = datetime.now(UTC)
    seen = {}

    async def list_by_user(user_id, limit):
        seen["user"] = user_id
        return [
            (uuid4(), "Q3 revenue", "what was q3 revenue", 4, now, now),
            (uuid4(), None, "a very long first question " * 5, 2, now, now),
            (uuid4(), None, None, 1, now, now),
        ]

    conversations = asyncio.run(ConversationService(NS(list_by_user=list_by_user)).get_summaries(parse_user_id("admin")))
    assert seen["user"] == "admin"  # conversations are private, the admin lists only their own
    assert conversations[0].title == "Q3 revenue"
    assert conversations[1].title.startswith("a very long first question") and conversations[1].title.endswith("…")
    assert len(conversations[1].title) == 60
    assert conversations[2].title == "Untitled"


def test_transcript_is_owner_only_and_ordered():
    from src.gateway.services.conversations import ConversationService

    svc, messages = make_service(lambda request: httpx.Response(200, content=ndjson({"type": "answer", "content": "Revenue grew."})))
    conversation_id, _ = run_turn(svc, ALICE, PostChatRequestDTO(message="How is revenue?"))
    from datetime import UTC, datetime
    for m in messages.items:
        m.created_at = datetime.now(UTC)  # set by the database in production
    conversation_svc = ConversationService(svc._conversation_repo, messages)

    transcript = asyncio.run(conversation_svc.get_messages(ALICE, conversation_id))
    assert [(m.role, m.content) for m in transcript] == [("user", "How is revenue?"), ("assistant", "Revenue grew.")]
    with pytest.raises(ConversationNotFoundError):
        asyncio.run(conversation_svc.get_messages(BOB, conversation_id))
    with pytest.raises(ConversationNotFoundError):
        asyncio.run(conversation_svc.get_messages(parse_user_id("admin"), conversation_id))
