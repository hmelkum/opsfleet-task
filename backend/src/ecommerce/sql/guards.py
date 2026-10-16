"""
Guard rails for model-authored SQL.

The statement the agent produces is treated as untrusted input: it must be a
single read-only query that reads only the virtual tables, by bare name. The
virtual tables (see ``virtual_tables.py``) are what make that safe: they carry
no PII columns and only the caller's entitled rows, so ``SELECT *`` is fine
as long as nothing else is reachable.

Messages are aimed at the model, since the tool hands the failure straight
back for a repair. They never name the underlying project or dataset.
"""
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from src.ecommerce.sql.exceptions import SQLGuardError

DIALECT = "bigquery"

ALLOWED_TABLES = frozenset({"products", "order_items", "orders", "users"})

_ALLOWED_TABLES_TEXT = ", ".join(sorted(ALLOWED_TABLES))


def ensure_single_read_only_select(query: str) -> exp.Query:
    """Validate *query* and return its parsed form.

    Raises :class:`SQLGuardError` with a message the model can act on.
    """
    if not (query or "").strip():
        raise SQLGuardError("Query is empty.")

    try:
        statements = [s for s in sqlglot.parse(query, read=DIALECT) if s is not None]
    except ParseError as e:
        raise SQLGuardError(f"The query could not be parsed: {_first_parse_error(e)}") from e

    if not statements:
        raise SQLGuardError("Query is empty.")

    if len(statements) > 1:
        raise SQLGuardError(
            "Only one statement per call is allowed; remove the ';' separators."
        )

    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise SQLGuardError(
            "Only read-only queries are allowed: the statement must be a SELECT "
            "(optionally with WITH)."
        )

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    clashes = cte_names & ALLOWED_TABLES
    if clashes:
        raise SQLGuardError(
            f"CTE name '{sorted(clashes)[0]}' clashes with a table name; rename the CTE."
        )

    for table in tree.find_all(exp.Table):
        _ensure_allowed_table(table, cte_names)

    return tree


def _ensure_allowed_table(table: exp.Table, cte_names: set[str]) -> None:
    if not isinstance(table.this, exp.Identifier):
        raise SQLGuardError(
            f"Table functions are not allowed. Query the tables directly: {_ALLOWED_TABLES_TEXT}."
        )

    if table.args.get("db") or table.args.get("catalog"):
        raise SQLGuardError(
            f"'{table.name}' must be referenced by its bare name, without a project "
            f"or dataset prefix. Available tables: {_ALLOWED_TABLES_TEXT}."
        )

    name = table.name.lower()
    if name not in ALLOWED_TABLES and name not in cte_names:
        raise SQLGuardError(
            f"Table '{table.name}' does not exist. Available tables: {_ALLOWED_TABLES_TEXT}."
        )


def _first_parse_error(e: ParseError) -> str:
    if e.errors:
        error = e.errors[0]
        return f"{error.get('description')} at line {error.get('line')}, column {error.get('col')}"
    return str(e)
