-- SP0: take conversation history away from the SQL tool's role.
--
-- Apply once to a database that predates SP0 Decision 7:
--   psql -d agentic_rag -f db/migrations/002_sql_tool_readonly_scope.sql
--   psql -d agentic_rag_test -f db/migrations/002_sql_tool_readonly_scope.sql
--
-- db/schema.sql no longer grants this, but a database built before that line changed
-- still carries the grant, and a grant that predates the decision is exactly the kind
-- that survives unnoticed.
--
-- Why this and not just the allowlist: tools/sql_tool.py validates the query text, but
-- a regex over SQL is not a security boundary -- `FROM "chat_history"` matched nothing
-- in it until SP0 fix round 1, while rag_readonly genuinely held SELECT. The role's
-- grants are what PostgreSQL itself enforces, so the grant is what has to go. The
-- remaining grants (`documents` only) keep the corpus readable, which is intended:
-- documents are shared by design (Decision 3).
--
-- Idempotent by construction: REVOKE of a privilege that is already absent is a no-op,
-- so re-running this file succeeds.
BEGIN;

REVOKE SELECT ON chat_history FROM rag_readonly;

COMMIT;
