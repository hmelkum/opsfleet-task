"""Tools the agent runs itself, not through the backend's MCP servers."""
from datetime import UTC, datetime

from langchain_core.tools import tool


@tool
def get_current_date() -> str:
    """Returns today's date (UTC) and weekday, e.g. "2026-10-16 (Friday)".

    Call it before working out a relative period such as "last month", "this quarter" or "Q1".
    """
    today = datetime.now(UTC).date()
    return f"{today.isoformat()} ({today:%A})"
