# SP0 — Ownership Foundation & Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every stored row an owner, close the missing-authorization gap on conversation reads, and install the component system that SP1–SP3 will build on.

**Architecture:** A new `sessions` table carries `user_id`; `chat_history` reaches its owner through a foreign key to it rather than a duplicated column. Two plain functions in `security.py` enforce ownership at the two `session_id` call sites, returning 404 for both "absent" and "not yours" so the two are indistinguishable. The RAG corpus stays deliberately shared, so `documents.user_id` records provenance only and search is unchanged. Frontend work is confined to installing shadcn-vue and aliasing its token names onto the existing `--c-*` variables — no existing component is touched.

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy 2.0 (sync), PostgreSQL 17 + pgvector, pytest; Vue 3 + TypeScript + Vite + Tailwind 3.4, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-21-sp0-ownership-foundation-design.md`

## Global Constraints

- Python interpreter is `/opt/homebrew/bin/python3.10`. Bare `python3` is shadowed by a shell function on this machine and is broken. Tests run as `../.venv/bin/pytest` from `backend/`.
- `psql` and `createdb` are keg-only. Use `/opt/homebrew/opt/postgresql@17/bin/psql` and `/opt/homebrew/opt/postgresql@17/bin/createdb`, or put that directory on `PATH` first.
- **Never run DDL or DML against `agentic_rag` except the migration in Task 1.** It holds the only real data. `agentic_rag_test` is disposable.
- `agentic_rag` currently holds exactly 1 user, 14 `chat_history` rows, 291 `documents` rows and 3 distinct session ids. The migration's backfill guard depends on that count being 1.
- Code, identifiers, commit messages and comments in English. Conventional Commits (`feat:`, `fix:`, `test:`, `chore:`, `docs:`).
- Ownership failures return **404**, never 403. A 403 confirms the resource exists, which is the fact being protected.
- No Tailwind v4 migration. Stay on Tailwind 3.4.19 with `darkMode: 'class'`.
- Every task ends with a green test run and a commit. No task is done on a passing import alone.

---

## File Structure

```text
ai/
├── db/
│   ├── schema.sql                              # MODIFY: sessions, FK, documents.user_id
│   └── migrations/001_ownership.sql            # CREATE: backfill for existing databases
│
├── backend/
│   ├── models.py                               # MODIFY: ChatSession, Document.user_id
│   ├── security.py                             # MODIFY: require_owned_session, get_or_create_session
│   ├── schemas.py                              # MODIFY: UserResponse
│   ├── config.py                               # MODIFY: sql_tool_allowed_tables  (Task 4)
│   ├── .env / .env.example                     # MODIFY: SQL_TOOL_ALLOWED_TABLES  (Task 4)
│   ├── services/document_service.py            # MODIFY: ingest_file takes user_id  (Task 3)
│   ├── routers/
│   │   ├── chat.py                             # MODIFY: both endpoints enforce ownership
│   │   ├── auth.py                             # MODIFY: GET /auth/me               (Task 2)
│   │   ├── documents.py                        # MODIFY: pass user.id               (Task 3)
│   │   └── upload.py                           # MODIFY: pass user.id               (Task 3)
│   └── tests/
│       ├── test_ownership.py                   # CREATE: the isolation suite
│       ├── test_models.py                      # MODIFY: create the parent session row
│       ├── test_chat_endpoint.py               # MODIFY: session_id fixture cleanup
│       ├── test_document_service.py            # MODIFY: pass a real user_id        (Task 3)
│       └── test_e2e_matrix.py                  # MODIFY: SQL case rewritten         (Task 4)
│
└── frontend/
    ├── package.json                            # MODIFY: shadcn-vue dependencies     (Task 5)
    ├── tailwind.config.js                      # MODIFY: ~17 alias entries          (Task 5)
    ├── src/lib/utils.ts                        # CREATE: cn()                       (Task 5)
    └── src/composables/useAuth.ts              # MODIFY: fetchMe()                  (Task 6)
```

---

## Task 1: Ownership foundation

This task cannot be split. The foreign key makes a `sessions` row mandatory before any `chat_history` insert, so the moment the schema lands every existing writer must already comply — including `POST /chat`. A task that shipped the schema alone would leave the suite red.

**Files:**
- Create: `db/migrations/001_ownership.sql`
- Modify: `db/schema.sql`
- Modify: `backend/models.py`
- Modify: `backend/security.py`
- Modify: `backend/routers/chat.py`
- Modify: `backend/tests/test_models.py:15-19`
- Modify: `backend/tests/test_chat_endpoint.py:24-31`
- Test: `backend/tests/test_ownership.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `models.ChatSession` — SQLAlchemy model for the `sessions` table, fields `id: str`, `user_id: int`, `title: str | None`, `created_at: datetime`, `updated_at: datetime`.
  - `security.require_owned_session(db: Session, session_id: str, user: User) -> ChatSession` — raises `HTTPException(404)` if absent or owned by someone else.
  - `security.get_or_create_session(db: Session, session_id: str, user: User) -> ChatSession` — same 404 rule, creates the row when absent, bumps `updated_at`, flushes.

- [ ] **Step 1: Write the failing migration test**

Create `backend/tests/test_ownership.py` with only this test for now:

```python
"""Ownership guarantees introduced by SP0.

Every test here builds its own users with uuid-suffixed names and removes them
afterwards, following the convention in tests/test_auth.py:10-24. Deleting a
User cascades to sessions and then to chat_history, so cleanup needs no
per-table bookkeeping.
"""
import subprocess
import uuid

import pytest

from database import SessionLocal
from models import User

PSQL = "/opt/homebrew/opt/postgresql@17/bin/psql"
TEST_DB = "agentic_rag_test"
MIGRATION = "db/migrations/001_ownership.sql"


def _psql(*args: str, db: str = TEST_DB) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PSQL, "-d", db, "-v", "ON_ERROR_STOP=1", *args],
        cwd="..",
        capture_output=True,
        text=True,
    )


def test_migration_001_is_idempotent():
    """The migration must be a no-op on a database that already carries its schema."""
    first = _psql("-f", MIGRATION)
    assert first.returncode == 0, first.stderr

    second = _psql("-f", MIGRATION)
    assert second.returncode == 0, second.stderr

    count = _psql("-tAc", "SELECT count(*) FROM sessions")
    assert count.returncode == 0, count.stderr
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && ../.venv/bin/pytest tests/test_ownership.py::test_migration_001_is_idempotent -v
```

Expected: FAIL — `db/migrations/001_ownership.sql` does not exist, so `psql` exits non-zero and the first assertion fails.

- [ ] **Step 3: Write the migration**

Create `db/migrations/001_ownership.sql`:

```sql
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

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chat_history_session_fk') THEN
        ALTER TABLE chat_history
            ADD CONSTRAINT chat_history_session_fk
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE;
    END IF;
END $$;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;

UPDATE documents
SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1)
WHERE user_id IS NULL;

COMMIT;
```

- [ ] **Step 4: Update `db/schema.sql` for fresh installs**

Insert this block immediately after the `users` table and before `CREATE TABLE IF NOT EXISTS chat_history`:

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id         VARCHAR(100) PRIMARY KEY,
    user_id    BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      VARCHAR(200),
    created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id, updated_at DESC);
```

Then change the `chat_history` table definition to carry the foreign key inline, so a fresh install gets it without the migration:

```sql
CREATE TABLE IF NOT EXISTS chat_history (
    id         BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       VARCHAR(20)  NOT NULL,
    message    TEXT         NOT NULL,
    created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chat_history_role_check CHECK (role IN ('user', 'assistant', 'system', 'tool'))
);
```

Add `user_id` to the `documents` table definition:

```sql
CREATE TABLE IF NOT EXISTS documents (
    id           BIGSERIAL PRIMARY KEY,
    filename     VARCHAR(255) NOT NULL,
    content      TEXT         NOT NULL,
    embedding    VECTOR(768),
    doc_metadata JSONB        NOT NULL DEFAULT '{}'::jsonb,
    user_id      BIGINT       REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Finally, record the read-only role decision next to the existing grants:

```sql
-- SQL-tool role: read-only, and deliberately NOT on users (password hashes).
-- `sessions` is excluded too, and on purpose: it holds conversation metadata, and the
-- SQL tool's reach is treated as LLM-visible. Do not add it to the GRANT below.
GRANT CONNECT ON DATABASE agentic_rag TO rag_readonly;
GRANT USAGE ON SCHEMA public TO rag_readonly;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM rag_readonly;
GRANT SELECT ON chat_history, documents TO rag_readonly;
```

- [ ] **Step 5: Recreate the test database from the updated schema**

`agentic_rag_test` currently holds hundreds of `chat_history` rows leaked by earlier e2e runs, with no users to attribute them to. The backfill guard would refuse to run there, correctly. It is disposable, so rebuild it from the schema instead of migrating it.

```bash
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
dropdb --if-exists agentic_rag_test
createdb agentic_rag_test
psql -d agentic_rag_test -f db/schema.sql
```

`dropdb` here destroys only a test database. Confirm the name is `agentic_rag_test` before running it.

- [ ] **Step 6: Apply the migration to the live database**

First confirm the precondition the guard depends on:

```bash
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
psql -d agentic_rag -tAc "SELECT count(*) FROM users"
```

Expected: `1`. If it prints anything else, STOP — the guard will refuse, and the attribution decision needs a human.

```bash
psql -d agentic_rag -f db/migrations/001_ownership.sql
```

Expected: `BEGIN`, `CREATE TABLE`, `CREATE INDEX`, `GRANT`, `DO`, `INSERT 0 3`, `DO`, `ALTER TABLE`, `UPDATE 291`, `COMMIT`.

- [ ] **Step 7: Run the migration test**

```bash
cd backend && ../.venv/bin/pytest tests/test_ownership.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit the schema**

```bash
git add db/schema.sql db/migrations/001_ownership.sql backend/tests/test_ownership.py
git commit -m "feat: add sessions table and document ownership columns"
```

- [ ] **Step 9: Add the ORM models**

In `backend/models.py`, add after the `User` class:

```python
class ChatSession(Base):
    """A conversation. Owns its chat_history rows through the FK on session_id.

    Invariant: a sessions row must exist before any chat_history row. The database
    enforces it; get_or_create_session() in security.py is the only sanctioned way to
    create one, and it flushes so the parent INSERT is emitted first. Note that the
    models declare no relationship(), so SQLAlchemy orders pending INSERTs by
    module.ClassName -- ChatHistory sorts before ChatSession -- and an explicit flush
    is what makes the order correct rather than the foreign key itself.
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

Change the `ChatHistory` model's `session_id` line to declare the foreign key:

```python
    session_id: Mapped[str] = mapped_column(String(100), ForeignKey("sessions.id", ondelete="CASCADE"))
```

Add to the `Document` model, after `doc_metadata`:

```python
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
```

And extend the import line at the top of the file:

```python
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
```

- [ ] **Step 10: Write the failing ownership tests**

Append to `backend/tests/test_ownership.py`:

```python
@pytest.fixture
def two_users(client):
    """Two real accounts, plus the auth headers for each. Yields (headers_a, headers_b)."""
    made = []
    for _ in range(2):
        username = f"own-{uuid.uuid4().hex[:8]}"
        client.post("/auth/register", json={"username": username, "password": "supersecret1"})
        token = client.post("/auth/login", json={"username": username, "password": "supersecret1"}).json()[
            "access_token"
        ]
        made.append({"Authorization": f"Bearer {token}"})
    yield made[0], made[1]
    session = SessionLocal()
    session.query(User).filter(User.username.like("own-%")).delete(synchronize_session=False)
    session.commit()
    session.close()


@pytest.fixture
def quiet_agent(monkeypatch):
    """Replace the live LLM call so these tests need no Ollama."""
    from agent.orchestrator import AgentResult
    from routers import chat as chat_router

    monkeypatch.setattr(
        chat_router,
        "run_agent",
        lambda db, message, history, image_path: AgentResult(answer="ok", tool_used=None, sources=[]),
    )


def test_chat_creates_session_owned_by_caller(client, two_users, quiet_agent):
    headers_a, _ = two_users
    session_id = f"own-{uuid.uuid4().hex[:8]}"

    response = client.post("/chat", headers=headers_a, json={"session_id": session_id, "message": "halo"})

    assert response.status_code == 200
    session = SessionLocal()
    row = session.query(ChatSession).filter_by(id=session_id).one()
    owner = session.query(User).filter_by(username=_username_of(headers_a)).one()
    session.close()
    assert row.user_id == owner.id


def test_chat_rejects_foreign_session_id(client, two_users, quiet_agent):
    """User B must not be able to write into user A's conversation."""
    headers_a, headers_b = two_users
    session_id = f"own-{uuid.uuid4().hex[:8]}"
    client.post("/chat", headers=headers_a, json={"session_id": session_id, "message": "rahasia A"})

    response = client.post("/chat", headers=headers_b, json={"session_id": session_id, "message": "halo dari B"})

    assert response.status_code == 404
    session = SessionLocal()
    rows = session.query(ChatHistory).filter_by(session_id=session_id).all()
    session.close()
    assert [r.message for r in rows] == ["rahasia A", "ok"], "B's message must not have been written"


def test_history_is_isolated_between_users(client, two_users, quiet_agent):
    """The IDOR regression: reading another user's conversation returns 404, not content."""
    headers_a, headers_b = two_users
    session_id = f"own-{uuid.uuid4().hex[:8]}"
    client.post("/chat", headers=headers_a, json={"session_id": session_id, "message": "rahasia A"})

    response = client.get(f"/chat/history?session_id={session_id}", headers=headers_b)

    assert response.status_code == 404
    assert "rahasia A" not in response.text


def test_history_requires_existing_session(client, two_users, quiet_agent):
    """An unknown id is 404, not an empty list -- the two must be indistinguishable."""
    headers_a, _ = two_users

    response = client.get(f"/chat/history?session_id=own-{uuid.uuid4().hex[:8]}", headers=headers_a)

    assert response.status_code == 404


def test_chat_second_message_reuses_the_same_session(client, two_users, quiet_agent):
    """Regression: both INSERTs are pending in one flush and SQLAlchemy orders them by
    class name, so without an explicit flush in get_or_create_session the chat_history
    INSERT is emitted first and every message on a new session fails on the foreign key."""
    headers_a, _ = two_users
    session_id = f"own-{uuid.uuid4().hex[:8]}"

    first = client.post("/chat", headers=headers_a, json={"session_id": session_id, "message": "satu"})
    second = client.post("/chat", headers=headers_a, json={"session_id": session_id, "message": "dua"})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
```

Add the helper at the top of the file, and **replace** the existing `from models import User` line from Step 1 with the wider import:

```python
from models import ChatHistory, ChatSession, User


def _username_of(headers: dict[str, str]) -> str:
    """Recover the username a test's headers belong to.

    A JWT's subject is the username, so read it back rather than threading a
    second value through every fixture.
    """
    import base64
    import json as _json

    payload = headers["Authorization"].split(" ", 1)[1].split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return _json.loads(base64.urlsafe_b64decode(padded))["sub"]
```

- [ ] **Step 11: Run the new tests to verify they fail**

```bash
cd backend && ../.venv/bin/pytest tests/test_ownership.py -v
```

Expected: the four ownership tests FAIL with 500 (the endpoints have no ownership logic yet, and `/chat` will actually fail on the foreign key since nothing creates the session row). `test_migration_001_is_idempotent` still passes.

- [ ] **Step 12: Add the ownership functions to `security.py`**

Append to `backend/security.py`, and extend its imports with `from models import ChatSession, User`:

```python
def require_owned_session(db: Session, session_id: str, user: User) -> ChatSession:
    """Return the caller's session.

    404 rather than 403 on both branches, deliberately: a 403 would confirm that the
    session exists, which is exactly the fact an attacker wants. "No such session" and
    "not yours" must be indistinguishable.
    """
    session = db.query(ChatSession).filter_by(id=session_id).one_or_none()
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown session")
    return session


def get_or_create_session(db: Session, session_id: str, user: User) -> ChatSession:
    """Return the caller's session, creating it on the first message.

    The explicit flush is load-bearing, not stylistic. `chat()` adds the ChatHistory
    row and calls a single `db.flush()`, so both INSERTs are pending in one unit of
    work. SQLAlchemy orders pending INSERTs by `Mapper._sort_key` -- module.ClassName --
    because these models declare no relationship() to give it a dependency edge, and
    `models.ChatHistory` sorts before `models.ChatSession`. Without the flush the
    chat_history INSERT goes first and the foreign key rejects it.
    """
    session = db.query(ChatSession).filter_by(id=session_id).one_or_none()
    if session is None:
        session = ChatSession(id=session_id, user_id=user.id)
        db.add(session)
        db.flush()
    elif session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown session")
    session.updated_at = func.now()
    return session
```

Add `from sqlalchemy import func` to that file's imports.

- [ ] **Step 13: Wire both chat endpoints**

In `backend/routers/chat.py`, change the import line and both handlers:

```python
from security import get_current_user, get_or_create_session, require_owned_session
```

In `chat()`, immediately after the `image_path = _resolve_image(...)` line:

```python
    get_or_create_session(db, payload.session_id, user)
```

In `history()`, change the body to:

```python
    require_owned_session(db, session_id, user)
    return (
        db.query(ChatHistory)
        .filter_by(session_id=session_id)
        .order_by(ChatHistory.id)
        .all()
    )
```

- [ ] **Step 14: Fix the two tests that write orphan rows**

`backend/tests/test_models.py` — `test_can_insert_and_read_chat_history` now needs a parent. Replace its body:

```python
def test_can_insert_and_read_chat_history(db):
    owner = User(username=f"model-{uuid.uuid4().hex[:8]}", password_hash="x", role="USER")
    db.add(owner)
    db.flush()
    db.add(ChatSession(id="test-session", user_id=owner.id))
    db.flush()
    db.add(ChatHistory(session_id="test-session", role="user", message="halo"))
    db.flush()
    row = db.query(ChatHistory).filter_by(session_id="test-session").one()
    assert row.message == "halo"
    assert row.created_at is not None
```

Its imports become:

```python
import uuid

import pytest
from sqlalchemy import text

from database import SessionLocal
from models import ChatHistory, ChatSession, Document, User
```

`backend/tests/test_chat_endpoint.py` — the `session_id` fixture currently deletes only `chat_history` rows, which the cascade now handles. Replace the fixture so it also removes the session row explicitly:

```python
@pytest.fixture
def session_id() -> str:
    sid = f"test-{uuid.uuid4().hex[:8]}"
    yield sid
    session = SessionLocal()
    session.query(ChatSession).filter_by(id=sid).delete(synchronize_session=False)
    session.commit()
    session.close()
```

and add `ChatSession` to that file's `from models import ...` line.

- [ ] **Step 15: Run the backend suite**

`pytest.ini` declares the `integration` marker but does not exclude it via `addopts`, so a bare `pytest` collects the e2e matrix too. Run the fast suite first:

```bash
cd backend && ../.venv/bin/pytest -m "not integration" -v
```

Expected: PASS.

Then the integration matrix, which needs live Postgres and Ollama:

```bash
cd backend && ../.venv/bin/pytest tests/test_e2e_matrix.py -v -m integration
```

Expected: PASS with **no edit to that file** — this is the Decision 6 tripwire from the spec. Every case posts a fresh `session_id` via `_ask()`, so all of them now take the session-creation path. If any case needs changing, stop and review Decision 6 before continuing rather than editing the test.

- [ ] **Step 16: Commit**

```bash
git add backend/models.py backend/security.py backend/routers/chat.py \
        backend/tests/test_ownership.py backend/tests/test_models.py backend/tests/test_chat_endpoint.py
git commit -m "feat: enforce session ownership on the chat endpoints"
```

---

## Task 2: `GET /auth/me`

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/routers/auth.py`
- Test: `backend/tests/test_ownership.py` (append)

**Interfaces:**
- Consumes: `security.get_current_user` (existing).
- Produces: `GET /auth/me` → `{"username": str, "role": str, "created_at": datetime}`. Task 6 consumes this from the frontend.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_ownership.py`:

```python
def test_auth_me_returns_username_and_role(client, two_users):
    headers_a, _ = two_users

    response = client.get("/auth/me", headers=headers_a)

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == _username_of(headers_a)
    assert body["role"] == "USER"
    assert body["created_at"]


def test_auth_me_rejects_missing_token(client):
    assert client.get("/auth/me").status_code == 401
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd backend && ../.venv/bin/pytest tests/test_ownership.py -k auth_me -v
```

Expected: FAIL with 404 — the route does not exist.

- [ ] **Step 3: Add the response schema**

Append to `backend/schemas.py`:

```python
class UserResponse(BaseModel):
    username: str
    role: str
    created_at: datetime
```

- [ ] **Step 4: Add the endpoint**

In `backend/routers/auth.py`, extend the imports and add the route:

```python
from schemas import LoginRequest, TokenResponse, UserResponse
```

```python
@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> User:
    """Identity for the signed-in caller.

    Not stale-token handling: the frontend's axios interceptor already clears the
    token and reloads on any non-auth 401. This exists because username and
    created_at have no other source -- the login response carries only the role.
    """
    return user
```

Add `from security import create_access_token, get_current_user, hash_password, verify_password` to that file's imports.

- [ ] **Step 5: Run the tests**

```bash
cd backend && ../.venv/bin/pytest tests/test_ownership.py -k auth_me -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/schemas.py backend/routers/auth.py backend/tests/test_ownership.py
git commit -m "feat: add GET /auth/me"
```

---

## Task 3: Document uploader provenance

**Files:**
- Modify: `backend/services/document_service.py:54`
- Modify: `backend/routers/documents.py:30`
- Modify: `backend/routers/upload.py:30`
- Modify: `backend/tests/test_document_service.py:56`
- Test: `backend/tests/test_ownership.py` (append)

**Interfaces:**
- Consumes: `models.Document.user_id` (Task 1).
- Produces: `ingest_file(db: Session, path: Path, user_id: int | None) -> int` — `user_id` defaults to `None` so the direct-call test needs no rewrite.

`ingest_file` has three call sites, not one. `POST /upload` is the path most uploads actually take — `frontend/src/components/UploadButton.vue:33` accepts `.png,.jpg,.jpeg,.webp,.pdf,.txt,.md` and `frontend/src/services/api.ts:112` sends every file to `/upload`. `upload.py:29-34` catches only `IngestError` and `EmbeddingError`, and `backend/main.py` registers no exception handler, so a missing argument escapes as an unhandled `TypeError` → 500.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ownership.py`:

```python
def test_upload_records_uploader(client, two_users, tmp_path, monkeypatch):
    """POST /upload is the path most uploads take, so provenance is checked there
    rather than only on POST /documents."""
    from services import document_service

    monkeypatch.setattr(document_service, "embed_texts", lambda texts: [[0.01] * 768 for _ in texts])
    headers_a, _ = two_users
    policy = tmp_path / "own-policy.txt"
    policy.write_text("kebijakan cuti tahunan 12 hari", encoding="utf-8")

    with policy.open("rb") as handle:
        response = client.post(
            "/upload", headers=headers_a, files={"file": ("own-policy.txt", handle, "text/plain")}
        )

    assert response.status_code == 200, response.text
    session = SessionLocal()
    owner = session.query(User).filter_by(username=_username_of(headers_a)).one()
    rows = session.query(Document).filter_by(filename="own-policy.txt").all()
    assert rows, "the document should have been ingested"
    assert {row.user_id for row in rows} == {owner.id}
    session.query(Document).filter_by(filename="own-policy.txt").delete(synchronize_session=False)
    session.commit()
    session.close()
```

Extend that file's `from models import ...` line with `Document`.

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && ../.venv/bin/pytest tests/test_ownership.py::test_upload_records_uploader -v
```

Expected: FAIL — `rows[0].user_id` is `None`, because nothing passes an owner yet.

- [ ] **Step 3: Change the signature**

In `backend/services/document_service.py`, change line 54 and the `Document(...)` construction:

```python
def ingest_file(db: Session, path: Path, user_id: int | None = None) -> int:
    """Load, clean, chunk, embed, and store a file. Returns the chunk count.

    user_id records provenance only. The corpus is shared by design, so retrieval
    ignores it; it exists so per-user filtering is a one-line change later rather
    than another migration.
    """
```

```python
            Document(
                filename=path.name,
                content=chunk,
                embedding=vector,
                user_id=user_id,
                doc_metadata={"chunk_index": index, "chunk_count": len(chunks), "source": str(path)},
            )
```

- [ ] **Step 4: Pass the owner at both production call sites**

`backend/routers/documents.py:30`:

```python
        chunks = ingest_file(db, stored_path, user.id)
```

`backend/routers/upload.py:30` — `user` is already in scope from `Depends(get_current_user)` at line 19:

```python
            ingest_file(db, stored, user.id)
```

- [ ] **Step 5: Run the test**

```bash
cd backend && ../.venv/bin/pytest tests/test_ownership.py::test_upload_records_uploader -v
```

Expected: PASS.

- [ ] **Step 6: Run the full suite**

```bash
cd backend && ../.venv/bin/pytest -v
```

Expected: PASS. `tests/test_document_service.py:56` calls `ingest_file(db, target)` with no owner, which the default covers — no edit needed there.

- [ ] **Step 7: Commit**

```bash
git add backend/services/document_service.py backend/routers/documents.py \
        backend/routers/upload.py backend/tests/test_ownership.py
git commit -m "feat: record the uploader on ingested documents"
```

---

## Task 4: Remove `chat_history` from the SQL tool's allowlist

**Files:**
- Modify: `backend/config.py:27`
- Modify: `backend/.env:20`
- Modify: `backend/.env.example:20`
- Modify: `backend/tests/test_e2e_matrix.py:135-138`
- Test: `backend/tests/test_ownership.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `tools.sql_tool._validate` rejects `chat_history`, raising `SqlRejected`. No signature changes.

Without this task, SP0 does not achieve its goal. `POST /chat` reaches the SQL tool for any authenticated user (`routers/chat.py:49-50` → `agent/registry.py:96-103`), `tools/sql_tool.py:_validate` checks statement shape and table names but carries no user or session parameter, and `registry.py:96-103` returns rows to the model as `repr(rows)`. Locking `GET /chat/history` while this stays open would close the front door and leave the side door ajar.

**The change is three files, not one.** `config.py` only holds a default; `.env` overrides it, and `config.py:34` sets `env_file=".env"`. Editing `config.py` alone changes nothing at runtime.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ownership.py`:

```python
def test_sql_tool_cannot_reach_chat_history():
    """The agent must not be able to read conversations through the SQL tool.

    Without this, locking GET /chat/history would not make conversations private:
    any authenticated user can ask the assistant to query the table instead.
    """
    from tools.sql_tool import SqlRejected, sql_query

    with pytest.raises(SqlRejected, match="not allowed"):
        sql_query("SELECT session_id, message FROM chat_history LIMIT 5")


def test_sql_tool_still_reaches_documents():
    """The corpus stays shared by design, so documents must remain queryable."""
    from tools.sql_tool import sql_query

    assert isinstance(sql_query("SELECT filename FROM documents LIMIT 1"), list)
```

- [ ] **Step 2: Run them to verify the first fails**

```bash
cd backend && ../.venv/bin/pytest tests/test_ownership.py -k sql_tool -v
```

Expected: `test_sql_tool_cannot_reach_chat_history` FAILS — the table is still allowlisted, so the query runs. `test_sql_tool_still_reaches_documents` passes.

- [ ] **Step 3: Remove the allowlist entry in all three places**

`backend/config.py:27`:

```python
    sql_tool_allowed_tables: list[str] = ["documents"]
```

`backend/.env:20` and `backend/.env.example:20`:

```text
SQL_TOOL_ALLOWED_TABLES=["documents"]
```

- [ ] **Step 4: Run the tests**

```bash
cd backend && ../.venv/bin/pytest tests/test_ownership.py -k sql_tool -v
```

Expected: both PASS.

- [ ] **Step 5: Rewrite the e2e case that asserted the opposite**

`backend/tests/test_e2e_matrix.py:135-138` currently proves the SQL tool *can* query `chat_history`. Replace that test with one asserting the tool reaches the shared corpus instead:

```python
def test_sql_001_statistics_question_uses_sql(client, auth, ingested_policy):
    """The SQL tool reaches the shared corpus. It deliberately cannot reach
    chat_history -- see docs/superpowers/specs/2026-09-21-sp0-ownership-foundation-design.md,
    Decision 7. The fixture is requested so the table is non-empty and a count is meaningful.
    """
    body = _ask(client, auth, "Berapa jumlah baris pada tabel documents?")
    assert body["tool_used"] == "sql_query"
    assert any(ch.isdigit() for ch in body["answer"])
```

- [ ] **Step 6: Run the integration matrix**

Requires live Postgres and Ollama.

```bash
cd backend && ../.venv/bin/pytest tests/test_e2e_matrix.py -v -m integration
```

Expected: PASS, including the rewritten case. `llama3.2:3b` may decline to emit `sql_query` for the reworded prompt — if `tool_used` comes back `None`, reword the question to name the table plainly (for example, "Pakai SQL: berapa baris di tabel documents?") rather than weakening the assertion. The assertion is the behaviour under test.

- [ ] **Step 7: Commit**

```bash
git add backend/config.py backend/.env.example backend/tests/test_e2e_matrix.py backend/tests/test_ownership.py
git commit -m "fix: remove chat_history from the sql tool allowlist"
```

`backend/.env` is git-ignored, so it is edited but not staged. Confirm the edit landed:

```bash
grep SQL_TOOL_ALLOWED_TABLES backend/.env
```

Expected: `SQL_TOOL_ALLOWED_TABLES=["documents"]`.

---

## Task 5: shadcn-vue and the token aliases

**Files:**
- Modify: `frontend/package.json` (via `npm install`)
- Modify: `frontend/tailwind.config.js`
- Modify: `frontend/src/style.css`
- Create: `frontend/src/lib/utils.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `cn(...inputs: ClassValue[])` in `frontend/src/lib/utils.ts`, imported by every generated shadcn-vue component. Tailwind colour keys `background`, `foreground`, `card`, `popover`, `secondary`, `muted`, `accent`, `destructive`, `input`, `ring`, and `primary.foreground` resolve to the existing palette. Tasks SP1–SP3 consume these.

The point of this task is that generated components inherit the current palette and dark mode with **no token rename and no Tailwind v4 migration**. No existing component is edited.

- [ ] **Step 1: Install the dependencies**

```bash
cd frontend && npm install reka-ui class-variance-authority clsx lucide-vue-next
```

`tailwind-merge` is deliberately **not** installed with the others. Its recent releases target Tailwind v4 only, and this project is on 3.4.19. Install it pinned, then verify:

```bash
cd frontend && npm install tailwind-merge@^2
npm ls tailwind-merge tailwindcss reka-ui
```

Expected: `tailwind-merge` resolves to a 2.x version and `tailwindcss` to 3.4.19. **If `npm install tailwind-merge` without the `@^2` pin resolves to 3.x, the build will produce silently missing utilities** — check `npm ls` output rather than assuming.

If `lucide-vue-next` prints a deprecation notice pointing at `@lucide/vue`, install that instead and use it in SP1; the name only matters once a component imports an icon.

- [ ] **Step 2: Verify the build still passes before touching config**

```bash
cd frontend && npm run build
```

Expected: PASS. This is the baseline — any breakage introduced later is attributable to the config change, not to the install.

- [ ] **Step 3: Create the `cn` helper**

Create `frontend/src/lib/utils.ts`:

```ts
import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Merge Tailwind classes with conflict resolution, so a component's default
 * classes can be overridden by a caller's without both landing in the output.
 * Every shadcn-vue component imports this.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
```

- [ ] **Step 4: Add the token aliases**

In `frontend/tailwind.config.js`, the `colors` block already defines `bg`, `surface`, `elevated`, `fg`, `subtle`, `faint`, `border`, `primary` (`DEFAULT`/`fg`/`soft`), `accent`, `danger`, `success`. Add these keys alongside them, inside the same `colors` object:

```js
        // shadcn-vue's expected names, aliased onto the --c-* palette above so
        // generated components inherit the current colours and dark mode with no
        // token rename. `primary` above already supplies DEFAULT and `fg`; shadcn
        // spells the foreground half `foreground`, so both are provided.
        background: 'rgb(var(--c-bg) / <alpha-value>)',
        foreground: 'rgb(var(--c-fg) / <alpha-value>)',
        card: {
          DEFAULT: 'rgb(var(--c-surface) / <alpha-value>)',
          foreground: 'rgb(var(--c-fg) / <alpha-value>)',
        },
        popover: {
          DEFAULT: 'rgb(var(--c-elevated) / <alpha-value>)',
          foreground: 'rgb(var(--c-fg) / <alpha-value>)',
        },
        secondary: {
          DEFAULT: 'rgb(var(--c-primary-soft) / <alpha-value>)',
          foreground: 'rgb(var(--c-fg) / <alpha-value>)',
        },
        muted: {
          DEFAULT: 'rgb(var(--c-primary-soft) / <alpha-value>)',
          foreground: 'rgb(var(--c-subtle) / <alpha-value>)',
        },
        accent: {
          DEFAULT: 'rgb(var(--c-primary-soft) / <alpha-value>)',
          foreground: 'rgb(var(--c-fg) / <alpha-value>)',
        },
        destructive: {
          DEFAULT: 'rgb(var(--c-danger) / <alpha-value>)',
          foreground: 'rgb(var(--c-danger-fg) / <alpha-value>)',
        },
        input: 'rgb(var(--c-border) / <alpha-value>)',
        ring: 'rgb(var(--c-primary) / <alpha-value>)',
      },
```

Note that `accent` already exists as a flat string. Replace that existing `accent: 'rgb(var(--c-accent) / <alpha-value>)',` line with the object form above, and keep `--c-accent` reachable as `accent-strong` so the gradient avatar's `to-accent` does not break:

```js
        'accent-strong': 'rgb(var(--c-accent) / <alpha-value>)',
```

`accent` is used in exactly five places, all of them as a gradient stop, never as `bg-accent` or `text-accent`. Change `to-accent` to `to-accent-strong` on each:

- `frontend/src/components/ChatBox.vue:88`
- `frontend/src/components/ChatBox.vue:127`
- `frontend/src/components/ChatBox.vue:157`
- `frontend/src/components/MessageBubble.vue:55`
- `frontend/src/components/LoginForm.vue:56`

Confirm the set is complete afterwards:

```bash
cd frontend && grep -rn "to-accent\b\|text-accent\b" src/
```

Expected: no output. This is the one place Task 5 touches existing components, and the name collision forces it.

- [ ] **Step 5: Add the missing `--c-danger-fg` token**

In `frontend/src/style.css`, add to `:root` after `--c-danger-soft: 254 242 242;`:

```css
    --c-danger-fg: 255 255 255;
```

and to `.dark` after `--c-danger-soft: 42 26 30;`:

```css
    --c-danger-fg: 26 20 48;
```

- [ ] **Step 6: Verify the aliases actually emit CSS**

Generate a probe file and build over it, so a typo fails here rather than silently inside a component in SP1:

```bash
cd frontend
printf '<div class="bg-background text-foreground border-input bg-card text-muted-foreground bg-destructive text-destructive-foreground text-primary-foreground bg-secondary bg-accent text-accent-foreground ring-ring"></div>' > /tmp/sp0-probe.html
npx tailwindcss -c tailwind.config.js -i src/style.css --content /tmp/sp0-probe.html -o /tmp/sp0-probe.css
grep -c -E '\.(bg-background|text-foreground|border-input|bg-card|text-muted-foreground|bg-destructive|text-destructive-foreground|text-primary-foreground|bg-secondary|bg-accent|text-accent-foreground|ring-ring)' /tmp/sp0-probe.css
```

Expected: `12`. A count below 12 means an alias name is wrong — fix it before continuing. `text-primary-foreground` in particular is undefined in the current config because it defines `primary.fg`, which is exactly the kind of gap this step exists to catch.

- [ ] **Step 7: Verify the app still builds and renders**

```bash
cd frontend && npm run build && npm test
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/tailwind.config.js \
        frontend/src/style.css frontend/src/lib/utils.ts frontend/src/components/
git commit -m "feat: adopt shadcn-vue token aliases on tailwind v3"
```

---

## Task 6: Load identity on boot

**Files:**
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/composables/useAuth.ts`
- Test: `frontend/src/composables/__tests__/useAuth.spec.ts` (create)

**Interfaces:**
- Consumes: `GET /auth/me` (Task 2).
- Produces: `useAuth()` additionally returns `username: Ref<string | null>` and `fetchMe(): Promise<void>`. SP3 and SP4 consume both.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/composables/__tests__/useAuth.spec.ts`:

```ts
import { describe, expect, it, vi } from 'vitest'

import { api } from '../../services/api'
import { useAuth } from '../useAuth'

// useAuth holds its state in module-level refs, so these tests drive that state
// through the refs it returns. Clearing localStorage between cases would not reset
// them, and the second test would then inherit the first test's token.
describe('useAuth.fetchMe', () => {
  it('populates username and role from the server, not from localStorage', async () => {
    const auth = useAuth()
    auth.token.value = 'a-token'
    auth.role.value = 'ADMIN' // deliberately wrong, to prove the server wins
    vi.spyOn(api, 'fetchMe').mockResolvedValue({
      username: 'siti',
      role: 'USER',
      created_at: '2026-09-21T00:00:00',
    })

    await auth.fetchMe()

    expect(auth.username.value).toBe('siti')
    expect(auth.role.value).toBe('USER')
  })

  it('clears the session when the stored token is rejected', async () => {
    const auth = useAuth()
    auth.token.value = 'stale-token'
    vi.spyOn(api, 'fetchMe').mockRejectedValue(new Error('401'))

    await auth.fetchMe()

    expect(auth.isAuthenticated.value).toBe(false)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd frontend && npm test -- useAuth
```

Expected: FAIL — `api.fetchMe` and `username` do not exist.

- [ ] **Step 3: Add the API call**

In `frontend/src/services/api.ts`, add to the `api` object after `login`:

```ts
  async fetchMe(): Promise<{ username: string; role: string; created_at: string }> {
    const { data } = await http.get('/auth/me')
    return data
  },
```

- [ ] **Step 4: Extend `useAuth`**

In `frontend/src/composables/useAuth.ts`, add a `username` ref beside `role`, expose it, and add the bootstrap function:

```ts
const username = ref<string | null>(localStorage.getItem(USERNAME_KEY))

  async function fetchMe(): Promise<void> {
    if (!token.value) return
    try {
      const me = await api.fetchMe()
      username.value = me.username
      role.value = me.role
      localStorage.setItem(USERNAME_KEY, me.username)
      localStorage.setItem(ROLE_KEY, me.role)
    } catch {
      logout()
    }
  }

  return { token, role, username, isAuthenticated, login, logout, fetchMe }
```

> **Post-execution corrections to the snippet above (both were ruled on during Task 6 and the shipped code differs from this text — do not re-apply it verbatim):**
>
> 1. `catch { logout() }` is wrong. It signs the person out on *any* failure — a backend restart, a dropped connection, a 500 — while their token is still valid. The rationale that the axios interceptor would cover this is also false: `services/api.ts:51` computes `isAuthCall = url.includes('/auth/')` and skips its own 401 handling for those URLs, so a 401 from `/auth/me` is deliberately deferred to this function. Narrow it to `if (axios.isAxiosError(error) && error.response?.status === 401) logout()`, with `import axios from 'axios'`.
> 2. `username.value = username` inside `login()` — required by Step 6, because `App.vue` mounts once so the boot fetch never re-fires after an in-session login — cannot be written that way: the `login(username, password)` parameter shadows the module-level `username` ref, so the assignment targets a string primitive (`TypeError: Cannot create property 'value' on string`). Rename the **parameter** to `name`, leaving the ref — the public interface — untouched.
>
> Also note that `vue-tsc -b` type-checks the spec files (`tsconfig.app.json` includes `src/**/*.ts`), so a test that passes under vitest can still fail the build. The gate is `npm test` **and** `npm run build`.

Set `username.value = null` and `localStorage.removeItem(USERNAME_KEY)` inside the existing `logout()`, and add `USERNAME_KEY` beside `TOKEN_KEY` / `ROLE_KEY` in `services/api.ts`:

```ts
export const USERNAME_KEY = 'agentic-rag-username'
```

- [ ] **Step 5: Run the test**

```bash
cd frontend && npm test -- useAuth
```

Expected: PASS.

- [ ] **Step 6: Call it on boot**

`useAuth` is consumed in three places — `App.vue:6` (`isAuthenticated`), `ChatBox.vue:12` (`logout`), `LoginForm.vue:9` (`login`). App.vue is the one that runs for the whole session, so the bootstrap belongs there. Change line 6 and add the mount hook:

```ts
const { isAuthenticated, fetchMe } = useAuth()

onMounted(() => {
  void fetchMe()
})
```

Add `onMounted` to that file's `vue` import. `fetchMe()` returns early when there is no token, so this is a no-op on the login screen.

- [ ] **Step 7: Run the full frontend suite and build**

```bash
cd frontend && npm test && npm run build
```

Expected: PASS, including the pre-existing `useChat.spec.ts`.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/services/api.ts frontend/src/composables/useAuth.ts \
        frontend/src/composables/__tests__/useAuth.spec.ts frontend/src/App.vue
git commit -m "feat: load identity from /auth/me on boot"
```

---

## Task 7: Record the results in `docs/DONE.md`

The spec's completion criteria 4 and 5 are claims about behaviour, and `docs/DONE.md` is this repository's place for recording that a claim was demonstrated rather than asserted. Its own header is explicit that every row is filled by running a command and pasting what it printed.

**Files:**
- Modify: `docs/DONE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code-facing.

- [ ] **Step 1: Run the isolation check and capture the output**

```bash
cd backend && ../.venv/bin/pytest tests/test_ownership.py -v
```

- [ ] **Step 2: Run the full backend suite and capture the summary line**

Needs live Postgres and Ollama, since this includes the integration matrix:

```bash
cd backend && ../.venv/bin/pytest -q
```

- [ ] **Step 3: Confirm the SQL tool refuses and the corpus is still reachable**

```bash
cd backend && ../.venv/bin/pytest tests/test_ownership.py -k sql_tool -v
```

- [ ] **Step 4: Add the rows**

At the bottom of the verdict summary table in `docs/DONE.md`, continuing the existing numbering, add rows for the two new requirements. Match the file's existing conventions: a verdict of **PASS**, **FAIL**, or **UNVERIFIED**, and a scope note where a row holds only under a stated limit.

| # | Section | Requirement | Verdict |
|---|---|---|---|
| 22 | Security | Conversation reads are owner-scoped (`GET /chat/history`, `POST /chat`) | paste what Step 1 printed |
| 23 | Security | The SQL tool cannot reach `chat_history` | paste what Step 3 printed |

Then add a short `## SP0 — ownership foundation` section below the table, with the run date, the exact commands from Steps 1–3, and their pasted output. Follow the existing house rule: nothing is ticked from memory or from the plan text.

- [ ] **Step 5: Commit**

```bash
git add docs/DONE.md
git commit -m "docs: record the SP0 isolation results"
```

---

## Deferred

- **Overlay animations.** Every shadcn-vue overlay primitive (dialog, dropdown, popover, tooltip) is styled with `animate-in`, `animate-out`, `zoom-in-95`, `slide-in-from-*` and their `data-[state]` variants, which come from an animation plugin rather than from colour tokens. `frontend/tailwind.config.js` has `plugins: []`. SP0 installs no overlay, so nothing breaks yet; when SP1 adds the first dialog, install `tailwindcss-animate` (the Tailwind v3 plugin — `tw-animate-css` is CSS-first and targets v4) and register it in `plugins`.
- **`documents.user_id` attribution is readable through the SQL tool.** `documents` stays allowlisted and rows come back whole, so any user can learn which uploader owns a document. Accepted: the corpus is shared, so the content was already readable by the same person, and `users` is not allowlisted so the id resolves to no username. If it ever needs to be private, add a column allowlist to `tools/sql_tool.py:_validate` rather than removing `documents`.
- **`docs/spec/agentic-rag-spec.md` §15** still instructs `npm create vite@latest -- --template react`, contradicting the Vue 3 implementation. That file is a verbatim copy of an external README, so it should be corrected by annotation rather than by editing the copy. Deferred to SP1.
