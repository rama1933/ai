import re

from sqlalchemy import text

from config import get_settings
from database import get_readonly_engine

# Any identifier appearing after FROM/JOIN/INTO/UPDATE must be in the allowlist.
TABLE_REF = re.compile(r"\b(?:from|join|into|update)\s+([a-zA-Z_][\w.]*)", re.IGNORECASE)
COMMENT = re.compile(r"(--[^\n]*|/\*.*?\*/)", re.DOTALL)


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
