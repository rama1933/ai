-- SP2: the admin console -- account deactivation, and the activity log.
--
-- Apply once to a database that predates SP2:
--   psql -d agentic_rag -f db/migrations/004_admin_console.sql
--   psql -d agentic_rag_test -f db/migrations/004_admin_console.sql
--
-- Idempotent by construction: IF NOT EXISTS makes a second run a no-op.
BEGIN;

-- Deactivation is the normal way to take an account away: it keeps the user's
-- sessions and documents attributable. Enforced per request in get_current_user,
-- so it bites on the next call rather than at token expiry.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS activity_log (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT       REFERENCES users(id) ON DELETE SET NULL,
    -- A deliberate snapshot, not a denormalisation to be normalised away: when the
    -- FK nulls out on user deletion the row must still name who did it.
    username   VARCHAR(100),
    action     VARCHAR(50)  NOT NULL,
    target     TEXT,
    -- Metadata only -- tool used, duration, chunk count, message length. Never
    -- message text: see SP2 Decision 3.
    detail     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS activity_log_created_idx ON activity_log (created_at DESC);
CREATE INDEX IF NOT EXISTS activity_log_action_idx ON activity_log (action, created_at DESC);

-- Required. `GRANT ... ON ALL TABLES IN SCHEMA public` (db/schema.sql) was evaluated
-- when schema.sql ran and covers only the tables that existed then, so it does not
-- reach this new table. Without this line every audited write dies with
-- `permission denied for table activity_log`, because the application connects as rag_app.
GRANT SELECT, INSERT, UPDATE, DELETE ON activity_log TO rag_app;
GRANT USAGE, SELECT ON SEQUENCE activity_log_id_seq TO rag_app;

-- No grant of any kind to rag_readonly, deliberately and permanently: the SQL tool's
-- reach is LLM-visible, and the log names every account and every admin action.
-- Do not add one.

COMMIT;
