import io
import json

import httpx
import readchar
from rich.console import Console

from src.chat.session import ChatSession
from src.gateway_api.client import GatewayAPIClient
from src.ui.confirm import confirm_deletion


CONFIRMATION = {
    "proposalId": "11111111-1111-1111-1111-111111111111",
    "expiresAt": "2099-01-01T00:00:00+00:00",
    "reports": [
        {"id": "r1", "title": "Calvin Klein Q1", "ownerId": "user_alice", "createdAt": "2026-10-15T18:00:00+00:00"},
        {"id": "r2", "title": "Calvin Klein Q2", "ownerId": "user_bob", "createdAt": "2026-10-15T18:05:00+00:00"},
    ],
}


def ndjson(*chunks) -> bytes:
    return "".join(json.dumps(c) + "\n" for c in chunks).encode()


class FakeGateway:
    """Answers each request with the next scripted response and records the request bodies."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.bodies = []
        self.users = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths = getattr(self, "paths", []) + [request.url.path]
        self.bodies.append(json.loads(request.content) if request.content else None)
        self.users.append(request.headers["X-User-Id"])
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_session(gateway, confirm=lambda console, count: False, debug=False, is_admin=False):
    console = Console(file=io.StringIO(), width=100, force_terminal=False, color_system=None)
    client = GatewayAPIClient("http://backend", "user_alice", transport=httpx.MockTransport(gateway))
    return ChatSession(client, console, "http://backend", is_admin=is_admin, user_name="alice", debug=debug, confirm=confirm), console


def output(console: Console) -> str:
    return console.file.getvalue()


def test_streams_answer_and_keeps_conversation():
    gateway = FakeGateway(
        httpx.Response(200, content=ndjson({"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}}, {"type": "answer", "content": "Revenue **grew**."})),
        httpx.Response(200, content=ndjson({"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}}, {"type": "answer", "content": "By 12%."})),
    )
    session, console = make_session(gateway)
    session.handle("How is revenue?")
    session.handle("By how much?")
    assert gateway.bodies == [{"message": "How is revenue?"}, {"message": "By how much?", "conversationId": "c1"}]
    assert gateway.users == ["user_alice", "user_alice"]
    assert "Revenue grew." in output(console) and "By 12%." in output(console)


def test_tool_calls_only_shown_in_debug():
    response = ndjson(
        {"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}},
        {"type": "tool_call", "content": {"name": "execute_sql_query", "args": {"query": "SELECT 42"}}},
        {"type": "tool_call", "content": {"name": "search_reports", "args": {"text": "calvin"}}},
        {"type": "answer", "content": "ok"},
    )
    quiet, quiet_console = make_session(FakeGateway(httpx.Response(200, content=response)))
    quiet.handle("q")
    loud, loud_console = make_session(FakeGateway(httpx.Response(200, content=response)), debug=True)
    loud.handle("q")
    assert "SELECT 42" not in output(quiet_console) and "search_reports" not in output(quiet_console)
    assert "SELECT 42" in output(loud_console)
    assert "search_reports" in output(loud_console) and "calvin" in output(loud_console)


def test_reasoning_is_shown_by_default_and_hidden_by_thoughts_toggle():
    response = ndjson(
        {"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}},
        {"type": "thought", "content": "Checking the discount rule."},
        {"type": "answer", "content": "ok"},
    )
    shown, shown_console = make_session(FakeGateway(httpx.Response(200, content=response)))
    shown.handle("q")
    assert "Checking the discount rule." in output(shown_console)

    hidden, hidden_console = make_session(FakeGateway(httpx.Response(200, content=response)))
    hidden.handle("/thoughts")
    hidden.handle("q")
    assert "Checking the discount rule." not in output(hidden_console)
    assert "ok" in output(hidden_console)


def test_reasoning_is_split_into_titled_steps():
    from src.ui.render import _reasoning_steps

    text = "**Defining New Customers**\n\nI'm deciding what counts.\n\n**Clarifying Definition**\n\nI will ask."
    assert _reasoning_steps(text) == [
        ("Defining New Customers", "I'm deciding what counts."),
        ("Clarifying Definition", "I will ask."),
    ]
    # a title that has only partly arrived is not shown as raw markup
    assert _reasoning_steps("**Defining New Customers**\n\nbody\n\n**Clarif") == [("Defining New Customers", "body")]
    assert _reasoning_steps("no titles at all") == [("", "no titles at all")]
    assert _reasoning_steps("") == []


def test_reasoning_collapses_to_numbered_titles_before_the_answer():
    response = ndjson(
        {"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}},
        {"type": "thought", "content": "**Defining New Customers**\n\nfirst step body\n\n"},
        {"type": "thought", "content": "**Clarifying Definition**\n\nsecond step body"},
        {"type": "answer", "content": "Do you mean sign-ups or first-time buyers?"},
    )
    session, console = make_session(FakeGateway(httpx.Response(200, content=response)))
    session.handle("how many new customers today?")
    shown = output(console)
    assert "1. Defining New Customers" in shown and "2. Clarifying Definition" in shown
    assert "first step body" not in shown and "second step body" not in shown
    assert "Do you mean sign-ups or first-time buyers?" in shown


def test_tool_calls_have_no_status_lines_and_debug_shows_arguments():
    response = ndjson(
        {"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}},
        {"type": "tool_call", "content": {"name": "execute_sql_query", "args": {"query": "SELECT 42"}}},
        {"type": "tool_call", "content": {"name": "get_db_schema", "args": {}}},
        {"type": "tool_call", "content": {"name": "some_new_tool", "args": {"x": 1}}},
        {"type": "answer", "content": "ok"},
    )
    quiet, quiet_console = make_session(FakeGateway(httpx.Response(200, content=response)))
    quiet.handle("q")
    loud, loud_console = make_session(FakeGateway(httpx.Response(200, content=response)), debug=True)
    loud.handle("q")
    for shown in (output(quiet_console), output(loud_console)):
        assert "Running a query" not in shown and "Reading the table structure" not in shown
    assert "SELECT 42" not in output(quiet_console)
    assert "SELECT 42" in output(loud_console) and "some_new_tool" in output(loud_console)


def test_long_tool_arguments_are_clipped_for_display():
    body = "x" * 5000
    response = ndjson(
        {"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}},
        {"type": "tool_call", "content": {"name": "save_report", "args": {"title": "t", "body": body}}},
        {"type": "answer", "content": "ok"},
    )
    loud, loud_console = make_session(FakeGateway(httpx.Response(200, content=response)), debug=True)
    loud.handle("q")
    shown = output(loud_console)
    assert body not in shown and "more characters" in shown


def test_confirmed_deletion_sends_structured_confirmation():
    seen = {}

    def confirm(console, count):
        seen["count"] = count
        return True

    gateway = FakeGateway(
        httpx.Response(200, content=ndjson(
            {"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}},
            {"type": "answer", "content": "These 2 reports match."},
            {"type": "confirmation_required", "content": CONFIRMATION},
        )),
        httpx.Response(200, content=ndjson({"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}}, {"type": "answer", "content": "Deleted 2 report(s)."})),
    )
    session, console = make_session(gateway, confirm=confirm, is_admin=True)
    session.handle("delete calvin klein reports")
    assert seen["count"] == 2
    assert gateway.bodies[1] == {"confirmation": {"proposalId": CONFIRMATION["proposalId"], "confirmed": True}, "conversationId": "c1"}
    text = output(console)
    assert "Calvin Klein Q2" in text and "bob" in text and "user_bob" not in text and "Deleted 2 report(s)." in text


def test_owner_column_only_for_admin():
    gateway = FakeGateway(
        httpx.Response(200, content=ndjson({"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}}, {"type": "confirmation_required", "content": CONFIRMATION})),
        httpx.Response(200, content=ndjson({"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}}, {"type": "answer", "content": "Okay, nothing was deleted."})),
    )
    session, console = make_session(gateway)
    session.handle("delete")
    assert "bob" not in output(console)
    assert gateway.bodies[1]["confirmation"]["confirmed"] is False


def test_agent_error_chunk_is_rendered():
    gateway = FakeGateway(httpx.Response(200, content=ndjson(
        {"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}},
        {"type": "error", "content": "The assistant is temporarily unavailable. Please try again in a moment."},
    )))
    session, console = make_session(gateway)
    session.handle("hi")
    assert "temporarily unavailable" in output(console)


def test_backend_down_is_a_friendly_message():
    session, console = make_session(FakeGateway(httpx.ConnectError("refused")))
    session.handle("hi")
    assert "Can't reach the backend at http://backend" in output(console)


def test_lost_conversation_starts_a_new_one():
    gateway = FakeGateway(
        httpx.Response(200, content=ndjson({"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}}, {"type": "answer", "content": "a"})),
        httpx.Response(404, json={"detail": "Conversation not found."}),
    )
    session, console = make_session(gateway)
    session.handle("first")
    session.handle("second")
    assert session.conversation_id is None
    assert "your next message starts a new one" in output(console)


def test_validation_error_is_shown():
    session, console = make_session(FakeGateway(httpx.Response(422, json={"detail": [{"msg": "Value error, bad input"}]})))
    session.handle("x")
    assert "Value error, bad input" in output(console)


def test_commands():
    session, console = make_session(FakeGateway())
    session.conversation_id = "c1"
    assert session.handle("/new") and session.conversation_id is None and session.in_conversation
    assert session.handle("/debug") and session.debug is True
    session.in_conversation = True
    assert session.handle("/help") and "/feedback" in output(console) and "/back" in output(console)
    assert session.handle("/nope") and "Unknown command" in output(console)
    assert session.handle("/exit") is False


def test_space_confirms_and_any_other_key_cancels():
    console = Console(file=io.StringIO())
    assert confirm_deletion(console, 3, read_key=lambda: readchar.key.SPACE, interactive=True) is True
    assert confirm_deletion(console, 3, read_key=lambda: readchar.key.ENTER, interactive=True) is False
    assert confirm_deletion(console, 3, read_key=lambda: "y", interactive=True) is False


def test_ctrl_c_at_confirmation_cancels():
    def interrupted():
        raise KeyboardInterrupt

    assert confirm_deletion(Console(file=io.StringIO()), 1, read_key=interrupted, interactive=True) is False


def test_non_interactive_falls_back_to_y_n(monkeypatch):
    console = Console(file=io.StringIO())
    monkeypatch.setattr(console, "input", lambda prompt: "y")
    assert confirm_deletion(console, 2, interactive=False) is True
    monkeypatch.setattr(console, "input", lambda prompt: "")
    assert confirm_deletion(console, 2, interactive=False) is False


def test_feedback_rates_the_last_turn():
    gateway = FakeGateway(
        httpx.Response(200, content=ndjson({"type": "conversation", "content": {"conversationId": "c1", "turnId": "t9"}}, {"type": "answer", "content": "a"})),
        httpx.Response(204),
    )
    session, console = make_session(gateway)
    session.handle("/feedback up")
    assert "open a conversation first" in output(console)
    session.in_conversation = True
    session.handle("/feedback up")
    assert "Nothing to rate yet" in output(console)
    session.handle("q")
    session.handle("/feedback down too long")
    assert gateway.paths[-1] == "/api/feedbacks"
    assert gateway.bodies[-1] == {"conversationId": "c1", "turnId": "t9", "rating": "down", "comment": "too long"}
    assert "feedback saved" in output(console)
    session.handle("/feedback meh")
    assert "Usage:" in output(console)


def test_debug_shows_turn_id():
    gateway = FakeGateway(httpx.Response(200, content=ndjson({"type": "conversation", "content": {"conversationId": "c1", "turnId": "t42"}}, {"type": "answer", "content": "a"})))
    session, console = make_session(gateway, debug=True)
    session.handle("q")
    assert "turn t42" in output(console)


def test_long_answer_is_printed_exactly_once():
    from src.ui.render import TailView, TurnRenderer

    lines = [f"- finding number {i}" for i in range(80)]
    console = Console(file=io.StringIO(), width=80, height=20, force_terminal=False, color_system=None)
    with TurnRenderer(console, debug=False) as renderer:
        for line in lines:
            renderer.answer_chunk(line + "\n")
    printed = [line.strip() for line in console.file.getvalue().splitlines()]
    assert printed.count("• finding number 0") == 1 and printed.count("• finding number 79") == 1

    # while streaming, the live view never exceeds the terminal height
    tail = Console(file=io.StringIO(), width=80, height=20, color_system=None)
    from rich.markdown import Markdown
    tail.print(TailView(Markdown("\n".join(lines))))
    rendered = tail.file.getvalue().splitlines()
    assert len(rendered) <= 18 and "finding number 79" in rendered[-1]


def test_main_menu_and_conversation_modes():
    gateway = FakeGateway(
        httpx.Response(200, content=ndjson({"type": "conversation", "content": {"conversationId": "c1", "turnId": "t1"}}, {"type": "answer", "content": "a"})),
    )
    session, console = make_session(gateway)
    assert not session.in_conversation and "alice ›" in session.prompt
    session.handle("What was revenue?")  # text in the main menu starts a conversation
    assert session.in_conversation and session.conversation_id == "c1" and "alice ›" in session.prompt
    assert "New conversation" in output(console) and "assistant ›" in output(console)
    session.handle("/back")
    assert not session.in_conversation and session.conversation_id is None


def test_history_and_open_resume_a_conversation():
    conversations = {"conversations": [
        {"id": "c7", "title": "Q3 revenue by category", "messageCount": 4, "createdAt": "2026-10-15T10:00:00+00:00", "lastMessageAt": "2026-10-15T11:00:00+00:00"},
        {"id": "c8", "title": "Returns by brand", "messageCount": 2, "createdAt": "2026-10-14T10:00:00+00:00", "lastMessageAt": "2026-10-14T11:00:00+00:00"},
    ]}
    transcript = {"messages": [
        {"role": "user", "content": "Which brands have the most returns?", "createdAt": "2026-10-14T10:00:00+00:00"},
        {"role": "assistant", "content": "**Allegra K** leads returns.", "createdAt": "2026-10-14T10:00:05+00:00"},
    ]}
    gateway = FakeGateway(
        httpx.Response(200, json=conversations),
        httpx.Response(200, json=transcript),
        httpx.Response(200, content=ndjson({"type": "conversation", "content": {"conversationId": "c8", "turnId": "t2"}}, {"type": "answer", "content": "more"})),
    )
    session, console = make_session(gateway)
    session.handle("/open 1")
    assert "Run /history first" in output(console)
    session.handle("/history")
    assert "Q3 revenue by category" in output(console) and gateway.paths[-1] == "/api/conversations"
    session.handle("/open 9")
    assert "between 1 and 2" in output(console)
    session.handle("/open 2")
    assert session.in_conversation and session.conversation_id == "c8"
    assert gateway.paths[-1] == "/api/conversations/c8/messages"
    assert "alice › Which brands have the most returns?" in output(console)
    assert "Allegra K leads returns." in output(console)  # Markdown rendered
    assert output(console).count("Returns by brand") == 2  # listed, then as the header
    session.handle("and by category?")
    assert gateway.bodies[-1] == {"message": "and by category?", "conversationId": "c8"}


def test_artifacts_list_and_read():
    artifacts = {"artifacts": [
        {"id": "a1", "kind": "report", "ownerId": "user_bob", "conversationId": "c1", "title": "Q3 report", "createdAt": "2026-10-15T10:00:00+00:00"},
    ]}
    detail = {"artifact": artifacts["artifacts"][0], "content": {"body": "## Summary\nRevenue grew 12%."}}
    gateway = FakeGateway(httpx.Response(200, json=artifacts), httpx.Response(200, json=detail))
    session, console = make_session(gateway, is_admin=True)
    session.handle("/artifacts")
    assert "Q3 report" in output(console) and "bob" in output(console) and "user_bob" not in output(console)
    session.handle("/artifacts 1")
    assert gateway.paths[-1] == "/api/artifacts/a1"
    assert "Revenue grew 12%." in output(console)
    assert not session.in_conversation  # browsing artifacts does not open a conversation


def test_listing_errors_are_friendly():
    session, console = make_session(FakeGateway(httpx.ConnectError("refused")))
    session.handle("/history")
    assert "Can't reach the backend" in output(console)


def test_display_name_drops_the_wire_prefix():
    from src.ui.render import display_name
    assert display_name("user_hayk") == "hayk"
    assert display_name("admin") == "admin"


def test_failed_transcript_fetch_does_not_switch_conversation():
    conversations = {"conversations": [{"id": "c7", "title": "T", "messageCount": 2, "createdAt": "2026-10-15T10:00:00+00:00", "lastMessageAt": "2026-10-15T11:00:00+00:00"}]}
    session, console = make_session(FakeGateway(httpx.Response(200, json=conversations), httpx.Response(404, json={"detail": "Conversation not found."})))
    session.handle("/history")
    session.handle("/open 1")
    assert not session.in_conversation and session.conversation_id is None
    assert "Conversation not found." in output(console)
