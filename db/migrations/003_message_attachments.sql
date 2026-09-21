-- SP1: attachments become part of the message that owns them.
--
-- Apply once to a database that predates SP1:
--   psql -d agentic_rag -f db/migrations/003_message_attachments.sql
--
-- Idempotent by construction: IF NOT EXISTS makes a second run a no-op.
-- rag_readonly holds no grant on chat_history, so the new column is out of the
-- SQL tool's reach for free; the GRANT block is deliberately untouched.
BEGIN;

ALTER TABLE chat_history
    ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMIT;
