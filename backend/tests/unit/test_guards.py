import pytest
from sqlglot import exp

from src.ecommerce.sql.exceptions import SQLGuardError
from src.ecommerce.sql.guards import ensure_single_read_only_select


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM users",
        "SELECT COUNT(*) FROM USERS",
        "SELECT * FROM `users`",
        "SELECT 1;",
        "SELECT state, SUM(oi.sale_price) FROM order_items oi JOIN users u ON u.id = oi.user_id GROUP BY state",
        "WITH monthly AS (SELECT DATE_TRUNC(DATE(created_at), MONTH) AS m, SUM(sale_price) AS r "
        "FROM order_items GROUP BY m) SELECT * FROM monthly ORDER BY m",
        "SELECT brand FROM products UNION ALL SELECT department FROM products",
        "SELECT * FROM orders WHERE user_id IN (SELECT id FROM users WHERE country = 'Brasil')",
        "SELECT x FROM UNNEST([1, 2, 3]) AS x",
    ],
)
def test_allowed_queries(query):
    assert isinstance(ensure_single_read_only_select(query), exp.Query)


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("", "empty"),
        ("   ", "empty"),
        (";", "empty"),
        ("SELECT 1; SELECT 2", "one statement"),
        ("SELECT 1; DELETE FROM orders WHERE TRUE", "one statement"),
        ("DELETE FROM orders WHERE TRUE", "read-only"),
        ("INSERT INTO orders (order_id) VALUES (1)", "read-only"),
        ("DROP TABLE users", "read-only"),
        ("UPDATE users SET age = 1 WHERE TRUE", "read-only"),
        ("DECLARE x INT64", "read-only"),
        ("SELECT * FROM thelook_ecommerce.users", "bare name"),
        ("SELECT email FROM `bigquery-public-data.thelook_ecommerce.users`", "bare name"),
        ("SELECT * FROM other_project.other_dataset.orders", "bare name"),
        ("SELECT * FROM INFORMATION_SCHEMA.TABLES", "does not exist"),
        ("SELECT * FROM events", "does not exist"),
        ("SELECT * FROM inventory_items", "does not exist"),
        ("SELECT * FROM users*", "does not exist"),
        ("SELECT * FROM my_tvf(1)", "Table functions"),
        ("WITH users AS (SELECT 1 AS id) SELECT * FROM users", "clashes"),
        ("SELECT FROM WHERE", "could not be parsed"),
    ],
)
def test_rejected_queries(query, reason):
    with pytest.raises(SQLGuardError) as ei:
        ensure_single_read_only_select(query)
    assert reason in str(ei.value)


def test_messages_never_name_the_dataset():
    with pytest.raises(SQLGuardError) as ei:
        ensure_single_read_only_select("SELECT * FROM `bigquery-public-data.thelook_ecommerce.users`")
    assert "bigquery-public-data" not in str(ei.value)
    assert "thelook_ecommerce" not in str(ei.value)


def test_model_cte_may_reference_tables():
    tree = ensure_single_read_only_select(
        "WITH big_spenders AS (SELECT user_id FROM order_items GROUP BY user_id HAVING SUM(sale_price) > 500) "
        "SELECT u.state, COUNT(*) FROM big_spenders b JOIN users u ON u.id = b.user_id GROUP BY u.state"
    )
    assert isinstance(tree, exp.Select)
