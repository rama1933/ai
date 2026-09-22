-- Agentic RAG schema. Apply with:
--   psql -d agentic_rag -f db/schema.sql
--   psql -d agentic_rag_test -f db/schema.sql

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'USER',
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT users_role_check CHECK (role IN ('ADMIN', 'USER', 'READ_ONLY'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id         VARCHAR(100) PRIMARY KEY,
    user_id    BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      VARCHAR(200),
    created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_history (
    id         BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       VARCHAR(20)  NOT NULL,
    message    TEXT         NOT NULL,
    attachments JSONB        NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chat_history_role_check CHECK (role IN ('user', 'assistant', 'system', 'tool'))
);

CREATE INDEX IF NOT EXISTS chat_history_session_idx
    ON chat_history (session_id, created_at);

CREATE TABLE IF NOT EXISTS documents (
    id           BIGSERIAL PRIMARY KEY,
    filename     VARCHAR(255) NOT NULL,
    content      TEXT         NOT NULL,
    embedding    VECTOR(768),
    doc_metadata JSONB        NOT NULL DEFAULT '{}'::jsonb,
    user_id      BIGINT       REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Cosine distance index; must match the operator used in rag_tool.py.
CREATE INDEX IF NOT EXISTS documents_embedding_idx
    ON documents USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS documents_filename_idx ON documents (filename);

CREATE TABLE IF NOT EXISTS activity_log (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT       REFERENCES users(id) ON DELETE SET NULL,
    -- A deliberate snapshot: the row must still name who acted after the FK nulls out.
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

-- Application role: full DML on every table.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rag_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO rag_app;

-- SQL-tool role: read-only, and deliberately NOT on users (password hashes).
-- `sessions` is excluded too, and on purpose: it holds conversation metadata, and the
-- SQL tool's reach is treated as LLM-visible. Do not add it to the GRANT below.
-- `chat_history` is excluded for the same reason as `sessions` (SP0 Decision 7): the
-- tool carries no user or session parameter, so any grant here is a read of every
-- user's conversation. Do not add it back either. Validating the SQL text in
-- tools/sql_tool.py is a fail-early convenience, not the boundary -- this grant is.
GRANT CONNECT ON DATABASE agentic_rag TO rag_readonly;
GRANT USAGE ON SCHEMA public TO rag_readonly;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM rag_readonly;
GRANT SELECT ON documents TO rag_readonly;
