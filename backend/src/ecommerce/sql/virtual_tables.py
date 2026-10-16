"""
Virtual tables: the only data the model's SQL can reach.

Each of ``products``, ``order_items``, ``orders`` and ``users`` is a CTE
prepended to the model's query. Because a CTE shadows a same-named table, the
model's bare names resolve to these instead of the base tables. Each CTE
projects only non-PII columns, so PII does not exist from the query's point of
view and ``SELECT *`` is safe.

In production this maps to BigQuery authorized views.
"""
import sqlglot
from sqlglot import exp

from src.ecommerce.bigquery.config import BaseBigQueryConfigService
from src.ecommerce.sql.guards import DIALECT

# Non-PII columns per table. Anything not listed (names, email, street address,
# postal code, city, coordinates) is not selectable.
VIRTUAL_TABLE_COLUMNS: dict[str, list[str]] = {
    "products": [
        "id", "name", "brand", "category", "department", "cost", "retail_price",
    ],
    "order_items": [
        "id", "order_id", "user_id", "product_id", "status", "sale_price",
        "created_at", "shipped_at", "delivered_at", "returned_at",
    ],
    "orders": [
        "order_id", "user_id", "status", "num_of_item",
        "created_at", "shipped_at", "delivered_at", "returned_at",
    ],
    "users": [
        "id", "age", "gender", "state", "country", "traffic_source", "created_at",
    ],
}


class VirtualTables:
    def __init__(self, bigquery_config_service: BaseBigQueryConfigService) -> None:
        dataset = bigquery_config_service.bigquery.dataset
        ctes = ",\n".join(
            f"{table} AS (SELECT {', '.join(columns)} FROM `{dataset}.{table}`)"
            for table, columns in VIRTUAL_TABLE_COLUMNS.items()
        )
        template = sqlglot.parse_one(f"WITH {ctes} SELECT 1", read=DIALECT)
        self._ctes: list[exp.CTE] = template.args["with_"].expressions

    def wrap(self, query: exp.Query) -> str:
        """Prepend the virtual tables to a query that already passed the guards."""
        wrapped = query.copy()
        ctes = [cte.copy() for cte in self._ctes]

        existing = wrapped.args.get("with_")
        if existing:
            existing.set("expressions", ctes + existing.expressions)
        else:
            wrapped.set("with_", exp.With(expressions=ctes))

        return wrapped.sql(dialect=DIALECT)
