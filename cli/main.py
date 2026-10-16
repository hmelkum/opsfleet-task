"""OpsFleet data agent CLI.

    uv run python main.py --user alice
    uv run python main.py --admin --debug
"""
import argparse
import re
import sys

from rich.console import Console

from src.chat.session import ChatSession
from src.gateway_api.client import GatewayAPIClient
from src.ui.render import USER_ID_PREFIX, display_name

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--user", metavar="USERNAME", help="chat as a regular user")
    identity.add_argument("--admin", action="store_true", help="chat as the administrator")
    parser.add_argument("--debug", action="store_true", help="show the SQL the agent runs")
    parser.add_argument("--url", default="http://localhost:8080", help="backend URL (default: %(default)s)")
    args = parser.parse_args()
    if args.user and not USERNAME_PATTERN.fullmatch(args.user):
        parser.error("USERNAME may contain letters, digits, '.', '_' and '-' (max 64)")
    return args


def main() -> int:
    args = parse_args()
    user_id = "admin" if args.admin else f"{USER_ID_PREFIX}{args.user}"

    console = Console()
    client = GatewayAPIClient(args.url, user_id)
    session = ChatSession(
        client,
        console,
        backend_url=args.url,
        is_admin=args.admin,
        user_name=display_name(user_id),
        debug=args.debug
    )

    console.print(
        f"[bold]OpsFleet data agent[/] · signed in as [cyan]{display_name(user_id)}[/]. "
        "Ask a question to start a conversation, or use a command:\n"
    )
    session.show_help()
    console.print()
    try:
        while True:
            try:
                line = console.input(session.prompt)
            except EOFError:
                break
            if not session.handle(line):
                break
            console.print()
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
    console.print("[dim]Bye.[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
