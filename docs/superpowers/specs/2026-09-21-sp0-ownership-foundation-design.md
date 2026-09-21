# SP0 — Ownership Foundation & Design System

**Status:** design, awaiting review
**Date:** 2026-09-21
**Parent decomposition:** SP1 conversation management · SP2 document management · SP3 account & settings · SP4 multi-user admin

**Goal:** Give every stored row an owner, close the missing-authorization gap in `/chat/history`, and install the component system that SP1–SP3 will build their pages on — so that no later sub-project has to migrate these tables a second time.

---

## 1. Why this sub-project exists

Three of the four requested subsystems read or write `chat_history` and `documents`. Both tables currently have no owner column, so every one of them would otherwise carry its own migration. SP0 pays that cost once.

It also closes a real defect. `backend/routers/chat.py:60`:

```python
@router.get("/chat/history", response_model=list[HistoryItem])
def history(
    session_id: str = Query(min_length=1, max_length=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ChatHistory]:
    return db.query(ChatHistory).filter_by(session_id=session_id).order_by(ChatHistory.id).all()
```

`get_current_user` proves the caller is logged in, but `user` is never referenced. The filter is `session_id` alone, so any authenticated caller who knows a session id reads another person's conversation. This is **missing authorization, not an open leak**: session ids are `session-<uuid4>` generated client-side in `frontend/src/composables/useChat.ts:17`, so they carry ~122 bits of entropy and cannot be enumerated. The severity is low today and rises the moment SP1 renders those ids in a sidebar and SP4 grants an admin role.

`documents` has the same shape of gap, but its resolution is different — see Decision 2.

---

## 2. Verified current state

Every claim below was read from the repository during this design.

| Fact | Evidence |
|---|---|
| `chat_history` has no owner column | `db/schema.sql:16-23` — `id, session_id, role, message, created_at` |
| `documents` has no owner column | `db/schema.sql:28-36` — `id, filename, content, embedding, doc_metadata, created_at` |
| No `sessions` table exists; session ids are bare strings | `db/schema.sql` — only `users`, `chat_history`, `documents` are created |
| RAG search is unfiltered across all documents | `backend/tools/rag_tool.py:26` — `db.query(Document.filename, Document.content, distance)`, no `WHERE` |
| Role infrastructure exists but is never called | `backend/security.py:17` `ROLES`, `:57` `require_role(...)` — zero call sites outside the definition |
| Tests point at `agentic_rag_test` but never create its schema | `backend/tests/conftest.py:12` sets `DATABASE_URL`; no DDL anywhere in the file |
| Tests isolate users by uuid-suffixed usernames + `LIKE` cleanup | `backend/tests/test_auth.py:10-24` |
| A 401 interceptor already clears the token and reloads | `frontend/src/services/api.ts:41-52` |
| Frontend has no router and no store | `frontend/package.json` — no `vue-router`, no `pinia` |
| Frontend tests exist for composables only | `frontend/src/composables/__tests__/useChat.spec.ts` |
| Live data volume is small | `users`=1, `chat_history`=14 rows, `documents`=291 rows, 3 distinct `session_id` |

---

## 3. Decisions

### Decision 1 — SP0 absorbs the `sessions` table (approved)

`chat_history.session_id` is a bare string with no referent. SP1 needs a session list with titles and ordering, which requires a real row per session. Creating it in SP0 rather than SP1 means `chat_history` is migrated exactly once. The alternative — add `user_id` to `chat_history` now, add `sessions` later — migrates the same table twice and leaves a denormalized column behind.

### Decision 2 — `chat_history` gets no `user_id`; ownership flows through `sessions` (approved)

With `sessions.user_id` present and a foreign key from `chat_history.session_id`, a direct `user_id` column on `chat_history` would be redundant. Ownership is resolved by joining through the session, which is a single primary-key lookup.

### Decision 3 — Document ownership is provenance only; the corpus stays shared (approved)

`documents.user_id` records who uploaded a file. RAG search remains unfiltered. A local knowledge base is more useful shared than partitioned, and this keeps `rag_tool.py` untouched. The column exists so that per-user filtering becomes a one-line change later rather than another migration.

### Decision 4 — Idempotent SQL migration, no Alembic (approved)

The project has no migration framework; `README.md` documents hand-applied `psql -f db/schema.sql` and `conftest.py` assumes the test schema already exists. Adding Alembic means a new dependency, a config file, and reconciling with `schema.sql` as the existing source of truth. One idempotent SQL file matches the established flow at a fraction of the cost.

### Decision 5 — Adopt shadcn-vue on Tailwind v3 via token aliasing (approved)

shadcn-vue components reference class names such as `bg-background`, `text-muted-foreground`, `border-input`, `bg-destructive`. Those names are mapped in `frontend/tailwind.config.js` onto the existing `--c-*` CSS variables from `frontend/src/style.css`. The result: shadcn components inherit the current palette and dark mode with no token rename, no Tailwind v4 migration, and no change to the six existing components.

Rejected: **Tailwind v4 migration** — a codemod plus a `style.css` rewrite on an application that currently passes 21/21 Definition-of-Done rows. Rejected: **stay fully custom** — SP1–SP3 would hand-write dialog, table, form, dropdown, and toast primitives.

### Decision 6 — `/chat` upserts its session; `GET /chat/history` requires one

`POST /chat` creates the session row on first message if it does not exist, owned by the caller. This keeps the existing client contract (frontend generates the id) and, more importantly, keeps `test_chat_endpoint.py` and `test_e2e_matrix.py` passing unmodified — they post arbitrary `session_id` values with no setup. `GET /chat/history` must not create rows, so it requires an existing owned session.

---

## 4. Schema changes

New file `db/migrations/001_ownership.sql`. `db/schema.sql` is updated in parallel so fresh installs get the same shape without the backfill block.

```sql
BEGIN;

CREATE TABLE IF NOT EXISTS sessions (
    id         VARCHAR(100) PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      VARCHAR(200),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id, updated_at DESC);

-- Refuse to guess if the backfill would be ambiguous.
DO $$
DECLARE n INT;
BEGIN
    SELECT count(*) INTO n FROM users;
    IF n > 1 THEN
        RAISE EXCEPTION 'backfill ambiguous: % users, expected exactly 1', n;
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

Notes:

- **Idempotent by construction.** `IF NOT EXISTS` on every object, a `NOT EXISTS` guard on the backfill insert and the constraint, and the `documents` update is self-limiting because the second run matches zero rows.
- **`title` is nullable and stays null after backfill.** SP1's list endpoint falls back to the first user message when `title IS NULL`. Deriving titles during backfill would be speculative work for a rendering detail SP1 owns.
- **`ON DELETE CASCADE` on `sessions.user_id`** — deleting a user removes their conversations, which cascades to `chat_history` through the new foreign key. This is intended: conversations are private.
- **`ON DELETE SET NULL` on `documents.user_id`** — the corpus is shared, so removing a user must not destroy knowledge other users rely on. The uploader becomes unknown rather than the documents becoming garbage.
- **The ambiguity guard is deliberate.** It is the one place where guessing could silently attribute one person's conversations to another. On this machine it cannot fire (one user), which is exactly why it costs nothing to keep.

---

## 5. Backend changes

### `backend/models.py`

Add a `ChatSession` model mirroring the table, and `user_id` on `Document`. Add a comment above `ChatHistory` recording the invariant that a `sessions` row must exist before any `chat_history` row, because the foreign key enforces it and a future writer of `chat_history` will otherwise learn this from a constraint violation.

### `backend/security.py`

Two plain functions, not FastAPI dependencies. `session_id` arrives in the request body for `POST /chat` and in the query string for `GET /chat/history`, so a `Depends`-style dependency cannot read both.

```python
def require_owned_session(db: Session, session_id: str, user: User) -> ChatSession:
    """Return the caller's session, or 404 if it does not exist or belongs to someone else."""
    session = db.query(ChatSession).filter_by(id=session_id).one_or_none()
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown session")
    return session


def get_or_create_session(db: Session, session_id: str, user: User) -> ChatSession:
    """Return the caller's session, creating it on first message."""
    session = db.query(ChatSession).filter_by(id=session_id).one_or_none()
    if session is None:
        session = ChatSession(id=session_id, user_id=user.id)
        db.add(session)
    elif session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown session")
    session.updated_at = func.now()
    return session
```

**404 rather than 403 is intentional.** A 403 would confirm that the session exists, which is exactly the fact an attacker wants. The two cases — "no such session" and "not yours" — must be indistinguishable.

### `backend/routers/chat.py`

- `chat()` calls `get_or_create_session(db, payload.session_id, user)` before writing history.
- `history()` calls `require_owned_session(db, session_id, user)` before querying.
- Both keep `HISTORY_TURNS = 10` and the existing `role.in_(("user", "assistant"))` filter unchanged.

### `backend/routers/auth.py`

Add `GET /auth/me`, returning `username`, `role`, and `created_at`. This is **not** stale-token handling — `frontend/src/services/api.ts:41` already clears the token and reloads on any non-auth 401. The value is that identity data currently reaches the frontend only as `role` from the login response; `username` and `created_at` have no source at all, and SP3 (profile, password change) and SP4 (user list) both need them.

### `backend/services/document_service.py` and `backend/routers/documents.py`

`ingest_file(db, path)` at `document_service.py:54` gains a `user_id: int` parameter, passed through to the `Document(...)` construction at line 65. `routers/documents.py` passes `user.id`.

### `backend/schemas.py`

Add `UserResponse` (`username`, `role`, `created_at`).

---

## 6. API surface after SP0

| Method | Path | Change |
|---|---|---|
| `POST` | `/auth/register` | unchanged |
| `POST` | `/auth/login` | unchanged |
| `GET` | `/auth/me` | **new** — `{username, role, created_at}` |
| `POST` | `/chat` | upserts its session, owned by the caller |
| `GET` | `/chat/history` | now requires an owned session; 404 otherwise |
| `POST` | `/documents` | records the uploader |
| `POST` | `/upload` | unchanged |

---

## 7. Frontend changes

Scoped deliberately small. SP0 installs the foundation; SP1 builds pages on it.

- **Dependencies:** `reka-ui`, `tailwind-merge`, `clsx`, `class-variance-authority`, `lucide-vue-next`.
- **`frontend/src/lib/utils.ts`** — the `cn()` helper (`clsx` + `twMerge`) that every shadcn-vue component imports.
- **`frontend/tailwind.config.js`** — approximately 15 alias entries mapping shadcn's expected names onto the existing tokens, e.g. `background: 'rgb(var(--c-bg) / <alpha-value>)'`, `foreground` → `--c-fg`, `muted` → `--c-subtle`, `card`/`popover` → `--c-surface`, `input`/`ring` → `--c-border`, `destructive` → `--c-danger`, `secondary` → `--c-primary-soft`. The `primary` key already exists and is compatible.
- **`frontend/src/composables/useAuth.ts`** — add `fetchMe()`, called once on boot, populating `username` and `role` from the server instead of trusting `localStorage`.
- **No component is modified.** All six existing components continue to work because nothing they reference is renamed or removed.

---

## 8. Testing

Backend tests follow the existing convention in `backend/tests/test_auth.py:10-24` — uuid-suffixed usernames with `LIKE`-based cleanup, so runs do not interfere.

| Test | Proves |
|---|---|
| `test_history_is_isolated_between_users` | **The IDOR regression.** User B requests user A's session id → 404, never A's messages. |
| `test_chat_rejects_foreign_session_id` | User B posting to A's session id → 404, and no row is written. |
| `test_chat_creates_session_owned_by_caller` | First message creates the `sessions` row with the correct `user_id`. |
| `test_history_requires_existing_session` | A well-formed but unknown session id → 404, not an empty list. |
| `test_auth_me_returns_username_and_role` | New endpoint shape. |
| `test_auth_me_rejects_missing_token` | 401. |
| `test_migration_001_is_idempotent` | `001_ownership.sql` applied twice: no error, row counts unchanged. |
| `test_documents_record_uploader` | `ingest_file` persists `user_id`. |
| existing suites | `test_chat_endpoint.py`, `test_e2e_matrix.py`, `test_auth.py` must pass **unmodified**. |

The last row is the load-bearing one. If any existing test needs editing to accommodate ownership, the upsert design in Decision 6 is wrong and should be revisited before proceeding.

Frontend: `frontend/src/composables/__tests__/useChat.spec.ts` must still pass. Add a case covering `fetchMe()` populating `username` from the server response.

---

## 9. Invariants and risks

- **A `sessions` row must exist before any `chat_history` row.** The foreign key enforces this; `get_or_create_session` satisfies it. `routers/chat.py` is the only writer of `chat_history` today. Recorded as a comment in `models.py` because a future writer will otherwise discover it through a constraint violation.
- **The migration assumes exactly one existing user.** It raises rather than guessing. Correct on this machine; it would need revisiting if the database ever holds more.
- **`sessions.id` keeps the client-generated format.** A client chooses its own session id, so it can create sessions under any id it likes — but only its own, and only when the id is unused. Collision with another user's id yields 404. This is acceptable because ids are uuid4-derived, and it is the property that keeps existing tests green.
- **No authorization change for documents.** RAG remains global by design; a user still retrieves chunks from documents they did not upload. That is the accepted consequence of Decision 3, not an oversight.

---

## 10. Out of scope

- Role enforcement. `require_role` (`security.py:57`) exists and is unused; SP4 wires it. SP0 adds no call site.
- Session list, rename, delete, search, and titles — SP1.
- Document list, delete, re-index — SP2.
- Password change, preferences, conversation export — SP3.
- Per-user RAG filtering — explicitly rejected in Decision 3.
- Tailwind v4 — explicitly rejected in Decision 5.
- `docs/spec/agentic-rag-spec.md` §15 still instructs `npm create vite --latest -- --template react`, which contradicts the Vue 3 implementation that exists. That spec is a verbatim copy of an external README (`docs/superpowers/plans/2026-09-21-agentic-rag-local.md`), so it is corrected by annotation, not by editing the copy. Deferred to SP1.

---

## 11. Completion criteria

SP0 is done when all of the following hold, each demonstrated by a command whose output is pasted rather than recalled:

1. `db/migrations/001_ownership.sql` applies cleanly to `agentic_rag` and is a no-op on a second run.
2. `agentic_rag_test` carries the same schema.
3. The full backend suite passes, with `test_chat_endpoint.py` and `test_e2e_matrix.py` unmodified.
4. A two-user isolation check returns 404 for the foreign session, both for `GET /chat/history` and `POST /chat`.
5. `GET /auth/me` returns `username`, `role`, and `created_at`.
6. `npm run build` succeeds and all six existing components render unchanged in light and dark mode.
7. `docs/DONE.md` gains a row recording the isolation result.
