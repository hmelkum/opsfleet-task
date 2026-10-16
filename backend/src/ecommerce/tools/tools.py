import asyncio
import json
import re
import time
from typing import Annotated, Any

from fastmcp.tools import tool
from pydantic import Field

from src.core.fastmcp.tools.results import ErrorToolResult, RetryGuidance
from src.core.observability.events import emit
from src.ecommerce.bigquery.safe_runner import BQQueryError, SafeBigQueryRunner
from src.ecommerce.sql.exceptions import SQLGuardError
from src.ecommerce.sql.guards import ensure_single_read_only_select
from src.ecommerce.sql.virtual_tables import VIRTUAL_TABLE_COLUMNS, VirtualTables
from src.ecommerce.tools.results import ExecuteSQLQueryToolResult, GetDBSchemaToolResult

# BigQuery reports positions in the executed SQL, which has the virtual tables prepended and is
# re-rendered, so they never match the model's query. Dropped to avoid misleading the repair.
_ERROR_POSITION = re.compile(r"\s+at \[\d+:\d+\]")


class EcommerceToolset:
    def __init__(
        self,
        runner: SafeBigQueryRunner,
        virtual_tables: VirtualTables
    ) -> None:
        self._runner = runner
        self._virtual_tables = virtual_tables
        self._ddl: str | None = None

    @tool
    async def get_db_schema(self) -> GetDBSchemaToolResult | ErrorToolResult:
        """
        Returns the schema of the retail database as ``CREATE TABLE``
        statements: every queryable table with its columns and BigQuery data
        types.

        Use it when you need exact table or column names or types to write a
        valid query for ``execute_sql_query``, or when the user asks what data
        is available. Tables are listed by bare name; query them exactly as
        listed, without a project or dataset prefix.

        The result is the same on every call: if an earlier result is still
        in front of you, reuse it instead of calling again.
        """
        if self._ddl is None:
            try:
                self._ddl = await asyncio.to_thread(self._render_ddl)
            except BQQueryError as e:
                return ErrorToolResult(
                    error=e.user_message,
                    retry=RetryGuidance.DO_NOT_RETRY
                )

        return GetDBSchemaToolResult(ddl=self._ddl)

    def _render_ddl(self) -> str:
        statements: list[str] = []
        for table, columns in VIRTUAL_TABLE_COLUMNS.items():
            types = {
                field["name"]: field["type"]
                for field in self._runner.get_table_schema(table)
            }
            column_lines = ",\n".join(
                f"    {column} {types.get(column, 'UNKNOWN')}"
                for column in columns
            )
            statements.append(f"CREATE TABLE {table} (\n{column_lines}\n);")
        return "\n\n".join(statements)

    @tool
    async def execute_sql_query(
        self,
        query: Annotated[str, Field(
            description=(
                "A single read-only BigQuery (GoogleSQL) statement starting with "
                "SELECT or WITH. Reference tables by bare name (products, "
                "order_items, orders, users); project- or dataset-qualified "
                "names, INFORMATION_SCHEMA, and table functions are rejected. "
                "Statement separators (';') are not allowed."
            )
        )],
    ) -> ExecuteSQLQueryToolResult | ErrorToolResult:
        """
        Runs a read-only SQL query against the retail database (BigQuery).

        The statement is validated before execution, so only a single
        ``SELECT``/``WITH`` query over the tables from ``get_db_schema`` is
        accepted; anything else fails with a message describing what to
        correct, and the query can be fixed and retried. Queries that would
        scan too much data are rejected before they run; narrow the date range
        or aggregate earlier.

        Returns ``columns`` and ``rows``. ``truncated: true`` means the row
        safety net cut the result and rows really are missing -- aggregate in
        SQL rather than paging through raw rows. An empty ``rows`` list is a
        valid answer, but check filters and literal values (e.g. status names)
        before concluding there is no data.
        """
        started = time.monotonic()
        try:
            tree = ensure_single_read_only_select(query)
        except SQLGuardError as e:
            emit("sql_query", sql=query, outcome="guard_rejected", error=str(e), duration_ms=self._ms(started))
            return ErrorToolResult(
                error=f"The query is invalid: {str(e).rstrip('.')}. Correct the query and retry.",
                retry=RetryGuidance.DIFFERENT_INPUT,
            )

        try:
            result = await asyncio.to_thread(
                self._runner.execute,
                self._virtual_tables.wrap(tree)
            )
        except BQQueryError as e:
            emit(
                "sql_query",
                sql=query,
                outcome="bq_error",
                error_kind=e.kind.value,
                repairable=e.llm_repairable,
                error=e.message,
                duration_ms=self._ms(started)
            )
            if e.llm_repairable:
                return ErrorToolResult(
                    error=f"BigQuery rejected the query: {_ERROR_POSITION.sub('', e.message).rstrip('.')}. Correct the statement and retry.",
                    retry=RetryGuidance.DIFFERENT_INPUT,
                )
            return ErrorToolResult(
                error=e.user_message,
                retry=RetryGuidance.DO_NOT_RETRY,
            )

        emit(
            "sql_query",
            sql=query,
            outcome="ok",
            rows=result.row_count,
            empty=result.is_empty,
            truncated=result.truncated,
            bytes_processed=result.bytes_processed,
            job_id=result.job_id,
            duration_ms=self._ms(started)
        )
        rows: list[dict[str, Any]] = json.loads(
            result.df.to_json(orient="records", date_format="iso", default_handler=str)
        )
        return ExecuteSQLQueryToolResult(
            columns=list(result.df.columns),
            rows=rows,
            truncated=result.truncated,
        )

    @staticmethod
    def _ms(started: float) -> int:
        return int((time.monotonic() - started) * 1000)
