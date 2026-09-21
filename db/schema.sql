-- Agentic RAG schema. Apply with:
--   psql -d agentic_rag -f db/schema.sql
--   psql -d agentic_rag_test -f db/schema.sql

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'USER',
    created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT users_role_check CHECK (role IN ('ADMIN', 'USER', 'READ_ONLY'))
);

CREATE TABLE IF NOT EXISTS chat_history (
    id         BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL,
    role       VARCHAR(20)  NOT NULL,
    message    TEXT         NOT NULL,
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
    created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Cosine distance index; must match the operator used in rag_tool.py.
CREATE INDEX IF NOT EXISTS documents_embedding_idx
    ON documents USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS documents_filename_idx ON documents (filename);

-- Application role: full DML on every table.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rag_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO rag_app;

-- SQL-tool role: read-only, and deliberately NOT on users (password hashes).
GRANT CONNECT ON DATABASE agentic_rag TO rag_readonly;
GRANT USAGE ON SCHEMA public TO rag_readonly;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM rag_readonly;
GRANT SELECT ON chat_history, documents TO rag_readonly;
