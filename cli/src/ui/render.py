import json
import re
from datetime import UTC, datetime
from typing import Any

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.segment import Segment
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

ASSISTANT_LABEL = Text("assistant ›", style="bold magenta")

USER_ID_PREFIX = "user_"

# Debug output is for reading, not for dumping: long arguments (e.g. a report body) are cut here
DEBUG_ARG_CHARS = 2000


def display_name(user_id: str) -> str:
    """``user_hayk`` -> ``hayk``; ``admin`` stays ``admin``. The prefix is only part of the wire format."""
    return user_id.removeprefix(USER_ID_PREFIX)


class TailView:
    """Renders only the last lines that fit the terminal.

    A live region taller than the terminal cannot be redrawn in place: the part
    that scrolled off is printed again on every refresh. Keeping the live view
    within one screen avoids that; the full answer is printed once at the end.
    """

    def __init__(self, renderable: RenderableType, margin: int = 2) -> None:
        self._renderable = renderable
        self._margin = margin

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        lines = console.render_lines(self._renderable, options.update(height=None), pad=False)
        visible = max(1, console.size.height - self._margin)
        for line in lines[-visible:]:
            yield from line
            yield Segment.line()


# Gemini's reasoning summaries are a short bold title per step, then a paragraph: "**Defining New Customers**"
_REASONING_HEADING = re.compile(r"^\s*\*\*(.+?)\*\*\s*$", re.MULTILINE)


def _reasoning_steps(text: str) -> list[tuple[str, str]]:
    """Splits a reasoning summary into (title, body) steps. Text without titles is one untitled step."""
    matches = list(_REASONING_HEADING.finditer(text))
    if not matches:
        return [("", text.strip())] if text.strip() else []
    steps = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        steps.append((match.group(1).strip(), _without_partial_title(text[match.end():end])))
    return steps


def _without_partial_title(body: str) -> str:
    """Drops a title that has only partly arrived ("**Clarif"), so it never shows as raw markup."""
    lines = body.rstrip().split("\n")
    if lines and lines[-1].lstrip().startswith("**") and lines[-1].count("**") < 2:
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _reasoning_view(steps: list[tuple[str, str]], expand_last: bool) -> RenderableType:
    """Numbered step titles; only the newest step shows its text, so earlier steps collapse as new ones arrive."""
    if not any(title for title, _ in steps):
        return Markdown("\n\n".join(body for _, body in steps), style="dim")
    parts: list[RenderableType] = []
    for number, (title, body) in enumerate(steps, 1):
        if parts:
            parts.append(Text(""))
        parts.append(Text(f"{number}. {title}", style="bold"))
        if expand_last and number == len(steps) and body:
            parts.append(Text(""))
            parts.append(Markdown(body, style="dim"))
    return Group(*parts)


def _clip(text: str) -> str:
    if len(text) <= DEBUG_ARG_CHARS:
        return text
    return f"{text[:DEBUG_ARG_CHARS]}\n… ({len(text) - DEBUG_ARG_CHARS} more characters)"


class TurnRenderer:
    """Renders one streamed turn: a spinner until text arrives, then the tail of the
    answer as live Markdown, and the whole answer once the turn is complete. While the
    model thinks, its reasoning shows as numbered steps with the newest one expanded;
    before the answer, the steps are printed collapsed to their titles."""

    def __init__(self, console: Console, debug: bool, show_thoughts: bool = True) -> None:
        self._console = console
        self._debug = debug
        self._show_thoughts = show_thoughts
        self._thoughts = ""
        self._answer = ""
        self._live = Live(
            Group(ASSISTANT_LABEL, Spinner("dots", text="Thinking…", style="cyan")),
            console=console,
            refresh_per_second=12,
            transient=True
        )

    def __enter__(self) -> "TurnRenderer":
        self._live.__enter__()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self._live.__exit__(*exc_info)
        if self._thoughts:
            view = _reasoning_view(_reasoning_steps(self._thoughts), expand_last=False)
            self._console.print(Panel(view, title="reasoning", border_style="dim", title_align="left"))
        if self._answer:
            self._console.print(ASSISTANT_LABEL)
            self._console.print(Markdown(self._answer))

    @property
    def answer(self) -> str:
        return self._answer

    def thought(self, text: str) -> None:
        if not self._show_thoughts:
            return
        self._thoughts += text
        view = _reasoning_view(_reasoning_steps(self._thoughts), expand_last=True)
        self._live.update(TailView(Group(
            ASSISTANT_LABEL,
            Spinner("dots", text="Thinking…", style="cyan"),
            Panel(view, title="reasoning", border_style="dim", title_align="left"),
        ), margin=3))

    def answer_chunk(self, text: str) -> None:
        self._answer += text
        self._live.update(Group(ASSISTANT_LABEL, TailView(Markdown(self._answer), margin=3)))

    def tool_call(self, call: dict[str, Any]) -> None:
        """Debug shows each tool call's arguments: SQL as SQL, anything else as JSON."""
        if not self._debug:
            return
        args = call.get("args") or {}
        if call["name"] == "execute_sql_query":
            body = Syntax(_clip(str(args.get("query", ""))), "sql", word_wrap=True)
            title = "SQL"
        else:
            body = Syntax(_clip(json.dumps(args, indent=2, ensure_ascii=False)), "json", word_wrap=True)
            title = call["name"]
        self._live.console.print(Panel(body, title=title, border_style="dim", title_align="left"))

    def error(self, message: str) -> None:
        self._live.console.print(Panel(message, border_style="red", title="Error", title_align="left"))


def render_deletion_preview(console: Console, confirmation: dict[str, Any], show_owner: bool) -> None:
    reports = confirmation["reports"]
    table = Table(title=f"Reports to delete ({len(reports)})", title_justify="left", header_style="bold")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Title")
    if show_owner:
        table.add_column("Owner", style="cyan")
    table.add_column("Created", style="dim")
    for i, report in enumerate(reports, 1):
        row = [str(i), report["title"]]
        if show_owner:
            row.append(display_name(report["ownerId"]))
        row.append(_local_date(report["createdAt"]))
        table.add_row(*row)
    console.print(table)
    minutes = _minutes_left(confirmation["expiresAt"])
    if minutes is not None:
        console.print(f"[dim]This request expires in about {minutes} min.[/]")


def _local_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def _minutes_left(value: str) -> int | None:
    try:
        expires_at = datetime.fromisoformat(value)
    except ValueError:
        return None
    return max(0, round((expires_at - datetime.now(UTC)).total_seconds() / 60))


def render_conversations(console: Console, conversations: list[dict[str, Any]]) -> None:
    if not conversations:
        console.print("[dim]No conversations yet. Type a question to start one.[/]")
        return
    table = Table(title="Your conversations", title_justify="left", header_style="bold")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Title")
    table.add_column("Messages", justify="right", style="dim")
    table.add_column("Last active", style="dim")
    for i, conversation in enumerate(conversations, 1):
        table.add_row(str(i), conversation["title"], str(conversation["messageCount"]), _local_date(conversation["lastMessageAt"]))
    console.print(table)
    console.print("[dim]/open <#> to continue one.[/]")


def render_artifacts(console: Console, artifacts: list[dict[str, Any]], show_owner: bool) -> None:
    if not artifacts:
        console.print("[dim]No saved reports yet. Ask for a report to create one.[/]")
        return
    table = Table(title="Saved artifacts", title_justify="left", header_style="bold")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Kind", style="dim")
    table.add_column("Title")
    if show_owner:
        table.add_column("Owner", style="cyan")
    table.add_column("Created", style="dim")
    for i, artifact in enumerate(artifacts, 1):
        row = [str(i), artifact["kind"], artifact["title"]]
        if show_owner:
            row.append(display_name(artifact["ownerId"]))
        row.append(_local_date(artifact["createdAt"]))
        table.add_row(*row)
    console.print(table)
    console.print("[dim]/artifacts <#> to read one.[/]")


def render_artifact(console: Console, detail: dict[str, Any]) -> None:
    artifact = detail["artifact"]
    console.print(Rule(f"{artifact['title']} · {_local_date(artifact['createdAt'])}", align="left"))
    body = detail["content"].get("body")
    console.print(Markdown(body) if body else "[dim](no content)[/]")
    console.print(Rule(style="dim"))


def render_conversation_header(console: Console, title: str) -> None:
    console.print(Rule(title, align="left", style="cyan"))


def render_transcript(console: Console, messages: list[dict[str, Any]], user_name: str) -> None:
    """Replays a conversation the way it looked live."""
    for message in messages:
        if message["role"] == "user":
            console.print(Text.assemble((f"{user_name} › ", "bold cyan"), message["content"]))
        else:
            console.print(ASSISTANT_LABEL)
            console.print(Markdown(message["content"]))
        console.print()
