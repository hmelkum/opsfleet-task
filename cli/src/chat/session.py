import time
from collections.abc import Callable
from typing import Any

from httpx import HTTPError
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from src.chat.models import ChatChunkType
from src.gateway_api.client import GatewayAPIClient
from src.gateway_api.exceptions import GatewayAPIError
from src.ui.confirm import confirm_deletion
from src.ui.render import (
    TurnRenderer,
    render_artifact,
    render_artifacts,
    render_conversation_header,
    render_conversations,
    render_deletion_preview,
    render_transcript,
)

MAIN_MENU_COMMANDS: dict[str, str] = {
    "/new": "Start a new conversation (or just type a question)",
    "/history": "List your conversations",
    "/open <#>": "Continue a conversation from /history",
    "/artifacts [#]": "List saved reports, or read one",
    "/debug": "Show or hide the tool calls (SQL included) and turn ids",
    "/thoughts": "Show or hide the model's reasoning summaries",
    "/help": "Show this help",
    "/exit": "Quit",
}

CONVERSATION_COMMANDS: dict[str, str] = {
    "/feedback up|down [comment]": "Rate the last answer",
    "/new": "Start another conversation",
    "/back": "Back to the main menu",
    "/history": "List your conversations",
    "/open <#>": "Switch to a conversation from /history",
    "/artifacts [#]": "List saved reports, or read one",
    "/debug": "Show or hide the tool calls (SQL included) and turn ids",
    "/thoughts": "Show or hide the model's reasoning summaries",
    "/help": "Show this help",
    "/exit": "Quit",
}


class ChatSession:
    """Two modes: the main menu (``in_conversation`` False) and a conversation."""

    def __init__(
        self,
        client: GatewayAPIClient,
        console: Console,
        backend_url: str,
        is_admin: bool,
        user_name: str,
        debug: bool = False,
        confirm: Callable[[Console, int], bool] = confirm_deletion
    ) -> None:
        self._client = client
        self._console = console
        self._backend_url = backend_url
        self._is_admin = is_admin
        self._user_name = user_name
        self._confirm = confirm
        self.debug = debug
        self.show_thoughts = True
        self.in_conversation = False
        self.conversation_id: str | None = None
        self.turn_id: str | None = None
        self._conversations: list[dict[str, Any]] = []
        self._artifacts: list[dict[str, Any]] = []

    @property
    def prompt(self) -> str:
        return f"[bold cyan]{escape(self._user_name)} ›[/] "

    def handle(self, line: str) -> bool:
        """Handles one line of input. Returns False when the user wants to quit."""
        line = line.strip()
        if not line:
            return True
        if line.startswith("/"):
            return self._command(line)
        if not self.in_conversation:
            self._start_conversation()
        self.send({"message": line})
        return True

    def send(self, body: dict[str, Any]) -> None:
        """Runs one turn, and the confirmation turn that follows when the agent proposed a deletion."""
        confirmation = self._turn(body)
        if confirmation is None:
            return

        render_deletion_preview(self._console, confirmation, show_owner=self._is_admin)
        confirmed = self._confirm(self._console, len(confirmation["reports"]))
        self._turn({"confirmation": {"proposalId": confirmation["proposalId"], "confirmed": confirmed}})

    # ------------------------------------------------------------------ conversation

    def _start_conversation(self) -> None:
        self.in_conversation = True
        self.conversation_id = None
        self.turn_id = None
        render_conversation_header(self._console, "New conversation")

    def _turn(self, body: dict[str, Any]) -> dict[str, Any] | None:
        if self.conversation_id:
            body = body | {"conversationId": self.conversation_id}

        confirmation: dict[str, Any] | None = None
        started = time.monotonic()
        try:
            with TurnRenderer(self._console, self.debug, self.show_thoughts) as renderer:
                for chunk in self._client.stream_chat(body):
                    match chunk["type"]:
                        case ChatChunkType.CONVERSATION:
                            self.conversation_id = chunk["content"]["conversationId"]
                            self.turn_id = chunk["content"]["turnId"]
                        case ChatChunkType.THOUGHT:
                            renderer.thought(chunk["content"])
                        case ChatChunkType.ANSWER:
                            renderer.answer_chunk(chunk["content"])
                        case ChatChunkType.TOOL_CALL:
                            renderer.tool_call(chunk["content"])
                        case ChatChunkType.CONFIRMATION_REQUIRED:
                            confirmation = chunk["content"]
                        case ChatChunkType.ERROR:
                            renderer.error(chunk["content"])
        except KeyboardInterrupt:
            self._console.print("[dim](stopped)[/]")
            return None
        except GatewayAPIError as e:
            self._gateway_error(e)
            return None
        except HTTPError:
            self._unreachable()
            return None
        if self.debug and self.turn_id:
            self._console.print(f"[dim]turn {self.turn_id} · {time.monotonic() - started:.1f}s[/]")
        return confirmation

    def _feedback(self, args: list[str]) -> None:
        if not self.in_conversation:
            self._console.print("[yellow]/feedback rates an answer: open a conversation first.[/]")
            return
        if not args or args[0].lower() not in ("up", "down"):
            self._console.print("[yellow]Usage:[/] /feedback up|down [comment]")
            return
        if not (self.conversation_id and self.turn_id):
            self._console.print("[yellow]Nothing to rate yet.[/]")
            return
        try:
            self._client.post_feedback(self.conversation_id, self.turn_id, args[0].lower(), " ".join(args[1:]) or None)
        except GatewayAPIError as e:
            self._console.print(f"[red]Feedback rejected:[/] {e.detail}")
            return
        except HTTPError:
            self._unreachable()
            return
        self._console.print("[dim]Thanks, feedback saved.[/]")

    # ------------------------------------------------------------------ history and artifacts

    def _history(self) -> None:
        conversations = self._fetch(self._client.get_conversations)
        if conversations is None:
            return
        self._conversations = conversations
        render_conversations(self._console, conversations)

    def _open(self, args: list[str]) -> None:
        if not self._conversations:
            self._console.print("[yellow]Run /history first, then /open <#>.[/]")
            return
        index = self._index(args, len(self._conversations), "/open <#>")
        if index is None:
            return
        conversation = self._conversations[index]
        messages = self._fetch(lambda: self._client.get_messages(conversation["id"]))
        if messages is None:
            return
        self.in_conversation = True
        self.conversation_id = conversation["id"]
        self.turn_id = None
        render_conversation_header(self._console, conversation["title"])
        render_transcript(self._console, messages, self._user_name)

    def _artifacts_command(self, args: list[str]) -> None:
        if not args:
            artifacts = self._fetch(self._client.get_artifacts)
            if artifacts is None:
                return
            self._artifacts = artifacts
            render_artifacts(self._console, artifacts, show_owner=self._is_admin)
            return

        if not self._artifacts:
            self._console.print("[yellow]Run /artifacts first, then /artifacts <#>.[/]")
            return
        index = self._index(args, len(self._artifacts), "/artifacts <#>")
        if index is None:
            return
        detail = self._fetch(lambda: self._client.get_artifact(self._artifacts[index]["id"]))
        if detail is not None:
            render_artifact(self._console, detail)

    def _fetch(self, call: Callable[[], Any]) -> Any | None:
        try:
            return call()
        except GatewayAPIError as e:
            self._console.print(f"[red]Request rejected:[/] {e.detail}")
        except HTTPError:
            self._unreachable()
        return None

    def _index(self, args: list[str], size: int, usage: str) -> int | None:
        if len(args) != 1 or not args[0].isdigit() or not 1 <= int(args[0]) <= size:
            self._console.print(f"[yellow]Usage:[/] {usage} with # between 1 and {size}")
            return None
        return int(args[0]) - 1

    # ------------------------------------------------------------------ commands

    def show_help(self) -> None:
        """The commands available in the current mode."""
        commands = CONVERSATION_COMMANDS if self.in_conversation else MAIN_MENU_COMMANDS
        table = Table(show_header=False, box=None, padding=(0, 2))
        for name, description in commands.items():
            table.add_row(f"[cyan]{escape(name)}[/]", description)
        self._console.print(table)

    def _gateway_error(self, e: GatewayAPIError) -> None:
        if e.status_code == 404 and self.conversation_id:
            self.conversation_id = None
            self._console.print("[yellow]That conversation is no longer available; your next message starts a new one.[/]")
        else:
            self._console.print(f"[red]Request rejected:[/] {e.detail}")

    def _unreachable(self) -> None:
        self._console.print(
            f"[red]Can't reach the backend at {self._backend_url}.[/] Is it running? (./runstr.sh)"
        )

    def _command(self, line: str) -> bool:
        command, *args = line.split()
        command = command.lower()
        match command:
            case "/exit" | "/quit":
                return False
            case "/new":
                self._start_conversation()
            case "/back":
                if self.in_conversation:
                    self.in_conversation = False
                    self.conversation_id = None
                    self.turn_id = None
                    self._console.print("[dim]Back to the main menu.[/]")
            case "/history":
                self._history()
            case "/open":
                self._open(args)
            case "/artifacts":
                self._artifacts_command(args)
            case "/feedback":
                self._feedback(args)
            case "/debug":
                self.debug = not self.debug
                self._console.print(f"[dim]Debug {'on: tool calls and turn ids will be shown' if self.debug else 'off'}.[/]")
            case "/thoughts":
                self.show_thoughts = not self.show_thoughts
                self._console.print(f"[dim]Reasoning {'on: the model\'s thinking is shown before each answer' if self.show_thoughts else 'off'}.[/]")
            case "/help":
                self.show_help()
            case _:
                self._console.print(f"[yellow]Unknown command {command}.[/] Type /help.")
        return True
