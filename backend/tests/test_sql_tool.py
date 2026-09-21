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


@pytest.mark.parametrize(
    "query",
    [
        'SELECT session_id FROM "chat_history" LIMIT 3',
        'SELECT session_id FROM "public"."chat_history" LIMIT 3',
    ],
)
def test_sql_query_rejects_quoted_table_names(query):
    """A quoted identifier must not slip past the allowlist.

    TABLE_REF's capture group cannot start with a quote, so `FROM "chat_history"`
    used to match nothing: the allowlist check ran over an empty list and passed,
    and rag_readonly genuinely held SELECT on the table. One pair of quote
    characters read every user's conversation.
    """
    with pytest.raises(sql_tool.SqlRejected, match="not allowed"):
        sql_tool.sql_query(query)


def test_sql_query_allows_the_quoted_form_of_an_allowed_table():
    """Quoting is ordinary SQL, so allowlisting must survive it rather than
    reject it -- the fix must not turn every quoted name into a rejection."""
    rows = sql_tool.sql_query('SELECT count(*) AS total FROM "documents"')
    assert isinstance(rows, list)
    assert "total" in rows[0]


def test_sql_query_rejects_pg_catalog_probing():
    with pytest.raises(sql_tool.SqlRejected, match="not allowed"):
        sql_tool.sql_query("SELECT * FROM pg_shadow")


@pytest.mark.parametrize(
    "query",
    [
        "WITH documents AS (DELETE FROM documents RETURNING *) SELECT * FROM documents",
        "WITH d AS (DELETE FROM documents) SELECT 1",
        "WITH x AS (INSERT INTO documents(filename,content) VALUES('a','b') RETURNING *) SELECT * FROM x",
        "WITH d AS (UPDATE documents SET content = 'x' RETURNING *) SELECT * FROM d",
        "SELECT * INTO newtable FROM documents",
    ],
)
def test_sql_query_rejects_data_modifying_ctes(query):
    with pytest.raises(sql_tool.SqlRejected):
        sql_tool.sql_query(query)


def test_sql_query_allows_keyword_substrings():
    rows = sql_tool.sql_query("SELECT count(*) AS update_count FROM documents")
    assert isinstance(rows, list)
    assert "update_count" in rows[0]


def test_sql_query_returns_rows_as_dicts():
    rows = sql_tool.sql_query("SELECT count(*) AS total FROM documents")
    assert isinstance(rows, list)
    assert "total" in rows[0]


def test_sql_query_caps_row_count():
    # `FROM documents` made this vacuous: it is a cross join against a table the test
    # database leaves empty, so the result was 0 rows and the cap was never reached.
    # generate_series with no FROM still passes _validate (SELECT, no table referenced)
    # and yields 500 rows deterministically, so the cap is what is actually measured.
    rows = sql_tool.sql_query("SELECT generate_series(1, 500) AS n LIMIT 500", max_rows=10)
    assert 0 < len(rows) <= 10
