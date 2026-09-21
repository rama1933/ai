import pytest

from tools import sql_tool


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM chat_history",
        "DROP TABLE documents",
        "UPDATE users SET role = 'ADMIN'",
        "INSERT INTO chat_history (session_id, role, message) VALUES ('a','user','b')",
        "TRUNCATE chat_history",
        "SELECT 1; DROP TABLE documents",
        "CREATE TABLE evil (id int)",
        "GRANT ALL ON users TO rag_readonly",
    ],
)
def test_sql_query_rejects_non_select(query):
    with pytest.raises(sql_tool.SqlRejected):
        sql_tool.sql_query(query)


def test_sql_query_rejects_table_outside_allowlist():
    with pytest.raises(sql_tool.SqlRejected, match="not allowed"):
        sql_tool.sql_query("SELECT username, password_hash FROM users")


def test_sql_query_rejects_pg_catalog_probing():
    with pytest.raises(sql_tool.SqlRejected, match="not allowed"):
        sql_tool.sql_query("SELECT * FROM pg_shadow")


def test_sql_query_returns_rows_as_dicts():
    rows = sql_tool.sql_query("SELECT count(*) AS total FROM chat_history")
    assert isinstance(rows, list)
    assert "total" in rows[0]


def test_sql_query_caps_row_count():
    rows = sql_tool.sql_query("SELECT generate_series(1, 500) AS n FROM chat_history LIMIT 500", max_rows=10)
    assert len(rows) <= 10
