"""Offline tests for EcommerceToolset through an in-memory MCP client. A fake runner stands in for BigQuery."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
from fastmcp import Client, FastMCP

from src.ecommerce.bigquery.config import BigQueryConfigModel
from src.ecommerce.bigquery.safe_runner import BQErrorKind, BQQueryError, QueryResult
from src.ecommerce.sql.virtual_tables import VirtualTables
from src.ecommerce.tools.tools import EcommerceToolset


class FakeRunner:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.executed: list[str] = []
        self.schema_calls = 0

    def execute(self, sql):
        self.executed.append(sql)
        if self.error:
            raise self.error
        return self.result

    def get_table_schema(self, table):
        self.schema_calls += 1
        return [
            {"name": "id", "type": "INTEGER"},
            {"name": "email", "type": "STRING"},
            {"name": "created_at", "type": "TIMESTAMP"},
        ]


def make_result(df: pd.DataFrame, truncated: bool = False) -> QueryResult:
    return QueryResult(df=df, row_count=len(df), truncated=truncated, bytes_processed=10, duration_ms=1)


def call(runner: FakeRunner, tool_name: str, args: dict | None = None) -> dict:
    async def _call() -> dict:
        toolset = EcommerceToolset(
            runner=runner,
            virtual_tables=VirtualTables(SimpleNamespace(bigquery=BigQueryConfigModel()))
        )
        mcp = FastMCP("test")
        mcp.add_tool(toolset.get_db_schema)
        mcp.add_tool(toolset.execute_sql_query)
        async with Client(mcp) as client:
            result = None
            for _ in range(2):  # second call exercises caching where relevant
                result = await client.call_tool(tool_name, args or {})
            return result.structured_content["result"]

    return asyncio.run(_call())


def test_tools_expose_only_model_facing_arguments():
    async def _list():
        toolset = EcommerceToolset(runner=FakeRunner(), virtual_tables=VirtualTables(SimpleNamespace(bigquery=BigQueryConfigModel())))
        mcp = FastMCP("test")
        mcp.add_tool(toolset.get_db_schema)
        mcp.add_tool(toolset.execute_sql_query)
        async with Client(mcp) as client:
            return {t.name: t.input_schema for t in await client.list_tools()}

    schemas = asyncio.run(_list())
    assert schemas["get_db_schema"].get("properties", {}) == {}
    assert list(schemas["execute_sql_query"]["properties"]) == ["query"]


def test_schema_lists_only_virtual_columns_and_is_cached():
    runner = FakeRunner()
    result = call(runner, "get_db_schema")
    assert result["success"] is True
    ddl = result["ddl"]
    assert "CREATE TABLE users (" in ddl and "id INTEGER" in ddl
    assert "email" not in ddl
    assert "thelook_ecommerce" not in ddl
    assert runner.schema_calls == 4  # once per table, second call served from cache


def test_query_runs_wrapped_in_virtual_tables():
    df = pd.DataFrame({"state": ["Texas"], "revenue": [Decimal("12.50")], "at": [pd.Timestamp("2024-01-01", tz="UTC")]})
    runner = FakeRunner(result=make_result(df, truncated=True))
    result = call(runner, "execute_sql_query", {"query": "SELECT state, SUM(sale_price) AS revenue FROM order_items GROUP BY state"})
    assert result == {
        "success": True,
        "columns": ["state", "revenue", "at"],
        "rows": [{"state": "Texas", "revenue": "12.50", "at": "2024-01-01T00:00:00.000Z"}],
        "truncated": True,
    }
    assert runner.executed[0].startswith("WITH products AS (")


def test_guard_rejection_is_repairable_and_never_reaches_bigquery():
    runner = FakeRunner()
    result = call(runner, "execute_sql_query", {"query": "SELECT email FROM `bigquery-public-data.thelook_ecommerce.users`"})
    assert result["success"] is False and result["retry"] == "different_input"
    assert "bare name" in result["error"]
    assert runner.executed == []


def test_repairable_bigquery_error_returns_technical_message():
    runner = FakeRunner(error=BQQueryError(BQErrorKind.INVALID_QUERY, "Unrecognized name: revenu at [1:8]"))
    result = call(runner, "execute_sql_query", {"query": "SELECT revenu FROM order_items"})
    assert result["retry"] == "different_input"
    assert result["error"] == "BigQuery rejected the query: Unrecognized name: revenu. Correct the statement and retry."


def test_non_repairable_bigquery_error_returns_safe_message():
    runner = FakeRunner(error=BQQueryError(BQErrorKind.TRANSIENT, "503 backend error on job xyz"))
    result = call(runner, "execute_sql_query", {"query": "SELECT 1"})
    assert result["retry"] == "do_not_retry"
    assert result["error"] == BQQueryError(BQErrorKind.TRANSIENT, "").user_message
    assert "503" not in result["error"]
