-- SP0: give every stored row an owner.
--
-- Apply once to a database that predates SP0:
--   psql -d agentic_rag -f db/migrations/001_ownership.sql
--
-- Idempotent by construction: every object uses IF NOT EXISTS, the backfill and
-- the constraint are guarded by NOT EXISTS, and the documents update matches zero
-- rows on a second run. Safe to re-run.
BEGIN;

CREATE TABLE IF NOT EXISTS sessions (
    id         VARCHAR(100) PRIMARY KEY,
    user_id    BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      VARCHAR(200),
    created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id, updated_at DESC);

-- Required. `GRANT ... ON ALL TABLES IN SCHEMA public` (db/schema.sql) was evaluated
-- when schema.sql ran and covers only the tables that existed then, so it does not
-- reach this new table. Without this line POST /chat dies with
-- `permission denied for table sessions`, because the application connects as rag_app.
GRANT SELECT, INSERT, UPDATE, DELETE ON sessions TO rag_app;

-- Refuse to guess, but only when there is something to guess about. Counting the
-- pending work keeps this a true no-op on a second run even after a second account
-- exists, and it catches the reverse case -- rows needing attribution with no user to
-- attribute them to -- that a bare `n > 1` test waves through into a NOT NULL violation.
DO $$
DECLARE n INT; pending INT;
BEGIN
    SELECT count(*) INTO n FROM users;
    SELECT count(*) INTO pending FROM chat_history h
        WHERE NOT EXISTS (SELECT 1 FROM sessions s WHERE s.id = h.session_id);
    IF pending > 0 AND n <> 1 THEN
        RAISE EXCEPTION 'backfill ambiguous: % unattributed sessions and % users, expected exactly 1 user',
            pending, n;
    END IF;
END $$;

INSERT INTO sessions (id, user_id, created_at, updated_at)
SELECT h.session_id,
       (SELECT id FROM users ORDER BY id LIMIT 1),
       MIN(h.created_at),
       MAX(h.created_at)
FROM chat_history h
WHERE NOT EXISTS (SELECT 1 FROM sessions s WHERE s.id = h.session_id)
GROUP BY h.session_id;

-- Guard on the column rather than a constraint name: a database built from
-- db/schema.sql already carries an inline FK on chat_history.session_id, and adding a
-- second, differently-named FK to the same column is not idempotent in any useful
-- sense -- it is duplicate schema. The guard asks for an FK *to sessions* specifically:
-- asking only whether some FK exists on the column would let an FK pointing elsewhere
-- suppress the one this migration is here to add.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_attribute a
          ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
        WHERE c.conrelid = 'chat_history'::regclass
          AND c.contype = 'f'
          AND c.confrelid = 'sessions'::regclass
          AND a.attname = 'session_id'
    ) THEN
        ALTER TABLE chat_history
            ADD CONSTRAINT chat_history_session_fk
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE;
    END IF;
END $$;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;

-- Same refusal to guess as the sessions backfill above: attribute the pre-SP0 corpus
-- only when there is exactly one account it could belong to. With two or more, every
-- NULL-owner document would silently become the lowest-id user's, and SP2 renders
-- "uploaded by" from this column -- a misattribution no later task can detect.
UPDATE documents
SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1)
WHERE user_id IS NULL
  AND (SELECT count(*) FROM users) = 1;

COMMIT;
