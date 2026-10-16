from types import SimpleNamespace

import sqlglot
from sqlglot import exp

from src.ecommerce.bigquery.config import BigQueryConfigModel
from src.ecommerce.sql.guards import ALLOWED_TABLES, DIALECT, ensure_single_read_only_select
from src.ecommerce.sql.virtual_tables import VIRTUAL_TABLE_COLUMNS, VirtualTables


DATASET = "bigquery-public-data.thelook_ecommerce"

PII_COLUMNS = {
    "first_name", "last_name", "email", "street_address",
    "postal_code", "city", "latitude", "longitude", "user_geom",
}


def wrap(query: str) -> str:
    virtual_tables = VirtualTables(SimpleNamespace(bigquery=BigQueryConfigModel(dataset=DATASET)))
    return virtual_tables.wrap(ensure_single_read_only_select(query))


def top_level_ctes(sql: str) -> list[exp.CTE]:
    return sqlglot.parse_one(sql, read=DIALECT).args["with_"].expressions


def test_virtual_tables_cover_exactly_the_allowed_tables():
    assert set(VIRTUAL_TABLE_COLUMNS) == ALLOWED_TABLES
    names = [cte.alias for cte in top_level_ctes(wrap("SELECT * FROM users"))]
    assert names == ["products", "order_items", "orders", "users"]


def test_virtual_tables_never_project_pii_or_star():
    for cte in top_level_ctes(wrap("SELECT 1")):
        projected = {e.alias_or_name for e in cte.this.expressions}
        assert projected == set(VIRTUAL_TABLE_COLUMNS[cte.alias])
        assert not projected & PII_COLUMNS, cte.alias
        assert not any(isinstance(e, exp.Star) for e in cte.this.expressions), cte.alias


def test_base_tables_are_only_reached_inside_virtual_tables():
    tree = sqlglot.parse_one(wrap("SELECT * FROM users"), read=DIALECT)
    qualified = [t for t in tree.find_all(exp.Table) if t.args.get("db")]
    assert {t.name for t in qualified} == ALLOWED_TABLES
    for t in qualified:
        assert f"{t.catalog}.{t.db}" == DATASET
        assert t.find_ancestor(exp.CTE).alias == t.name


def test_model_ctes_are_merged_into_one_with_clause():
    sql = wrap(
        "WITH monthly AS (SELECT DATE_TRUNC(DATE(created_at), MONTH) AS m, SUM(sale_price) AS r "
        "FROM order_items GROUP BY m) SELECT * FROM monthly ORDER BY m"
    )
    names = [cte.alias for cte in top_level_ctes(sql)]
    assert names == ["products", "order_items", "orders", "users", "monthly"]
    assert sql.count("WITH") == 1


def test_order_by_and_limit_stay_on_the_outer_query():
    tree = sqlglot.parse_one(
        wrap("SELECT brand, SUM(retail_price) AS r FROM products GROUP BY brand ORDER BY r DESC LIMIT 5"),
        read=DIALECT,
    )
    assert tree.args.get("order") is not None
    assert tree.args.get("limit") is not None


def test_union_queries_are_wrapped():
    sql = wrap("SELECT brand FROM products UNION ALL SELECT department FROM products")
    assert [cte.alias for cte in top_level_ctes(sql)] == ["products", "order_items", "orders", "users"]


def test_input_query_is_not_mutated():
    tree = ensure_single_read_only_select("SELECT * FROM users")
    before = tree.sql(dialect=DIALECT)
    VirtualTables(SimpleNamespace(bigquery=BigQueryConfigModel())).wrap(tree)
    assert tree.sql(dialect=DIALECT) == before
