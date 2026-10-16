"""
The structured deletion confirmation. The decision is sent as data
(``confirmed: true/false``), never as chat text the model would interpret.
"""
import sys
from collections.abc import Callable

import readchar
from rich.console import Console


def confirm_deletion(
    console: Console,
    count: int,
    read_key: Callable[[], str] = readchar.readkey,
    interactive: bool | None = None
) -> bool:
    """SPACE deletes, any other key cancels. Without a terminal, falls back to a y/N prompt (default No)."""
    noun = "report" if count == 1 else "reports"
    if interactive is None:
        interactive = sys.stdin.isatty()

    if not interactive:
        answer = console.input(f"Delete {count} {noun}? [y/N]: ")
        return answer.strip().lower() in ("y", "yes")

    console.print(f"Press [bold red]SPACE[/] to delete {count} {noun}, any other key to cancel.")
    try:
        key = read_key()
    except KeyboardInterrupt:
        key = ""
    return key == readchar.key.SPACE
