from typing import Any

from src.core.fastmcp.tools.results import SuccessToolResult


class GetDBSchemaToolResult(SuccessToolResult):
    ddl: str


class ExecuteSQLQueryToolResult(SuccessToolResult):
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool
