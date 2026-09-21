import re

from sqlalchemy import text

from config import get_settings
from database import get_readonly_engine

# Any identifier appearing after FROM/JOIN/INTO/UPDATE must be in the allowlist.
# The surrounding quotes are optional because PostgreSQL treats `FROM "chat_history"`
# as the same table as `FROM chat_history`: a pattern that could not start at a quote
# matched nothing there, so the allowlist ran over an empty list and the query went to
# the database. The role grant is the real boundary (db/migrations/002), but this
# layer must not be one pair of quote characters away from useless.
TABLE_REF = re.compile(r'\b(?:from|join|into|update)\s+"?([a-zA-Z_][\w.]*)"?', re.IGNORECASE)
COMMENT = re.compile(r"(--[^\n]*|/\*.*?\*/)", re.DOTALL)

# A statement that starts with WITH and only later says SELECT can still write:
# data-modifying CTEs (`WITH d AS (DELETE FROM documents) SELECT 1`) and
# SELECT ... INTO. Track string literals so a keyword inside a string is ignored,
# and match whole words only, so identifiers such as `update_time` survive.
STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
WRITE_KEYWORD = re.compile(
    r"\b(?:insert|update|delete|merge|truncate|drop|alter|create|grant|revoke|"
    r"copy|call|do|vacuum|reindex|refresh|comment|security|policy|into)\b",
    re.IGNORECASE,
)


class SqlRejected(ValueError):
    """The generated SQL is not something we are willing to execute."""


def _validate(query: str) -> str:
    stripped = COMMENT.sub(" ", query).strip().rstrip(";").strip()

    if ";" in stripped:
        raise SqlRejected("only a single statement is allowed")
    if not re.match(r"^(select|with)\b", stripped, re.IGNORECASE):
        raise SqlRejected("only SELECT (or WITH ... SELECT) statements are allowed")

    allowed = {t.lower() for t in get_settings().sql_tool_allowed_tables}
    for referenced in TABLE_REF.findall(stripped):
        if referenced.lower() not in allowed:
            raise SqlRejected(f"table {referenced!r} is not allowed; allowed: {sorted(allowed)}")

    # Fast rejection layer only: the rag_readonly role (no write grants) plus the
    # statement timeout remain the real boundary, this just fails early with a
    # clear error instead of leaning on PostgreSQL to refuse the write.
    match = WRITE_KEYWORD.search(STRING_LITERAL.sub("''", stripped))
    if match:
        raise SqlRejected(
            f"{match.group(0).upper()} is not allowed; only read-only SELECT statements are permitted"
        )
    return stripped


def sql_query(query: str, max_rows: int = 50) -> list[dict]:
    """Run a read-only SELECT against the allowlisted tables.

    Defence in depth: shape check, table allowlist, rag_readonly role (which has
    no write grants at all), and a server-side statement timeout.
    """
    statement = _validate(query)
    timeout_ms = get_settings().sql_tool_timeout_ms

    with get_readonly_engine().connect() as conn:
        conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
        result = conn.execute(text(statement))
        rows = result.mappings().fetchmany(max_rows)
    return [dict(row) for row in rows]
