# SP0 — Ownership Foundation & Design System

**Status:** design, awaiting review
**Date:** 2026-09-21
**Verification:** five independent lenses (SQL execution, code-change completeness, test impact, frontend, security) raised 14 findings across 19 agents; the blocker and major ones were then handed to skeptics instructed to kill them. Nine were refuted. Five survived and are folded in above:

- `test_models.py` is a second writer of `chat_history`, not just `routers/chat.py` (§8, §9).
- `ingest_file` has three call sites, not one (§5, §6).
- The SQL tool reads every user's `chat_history` regardless of ownership, so locking `GET /chat/history` alone would not have achieved this sub-project's goal (Decision 7).
- The migration guard fails in both directions — it aborts on a second run once a second account exists, and waves through rows needing attribution when there are no users (§4).
- `get_or_create_session` emits the `chat_history` INSERT before the `sessions` one, because the models declare no `relationship()` (§9).

Each survivor was **reproduced**, not reasoned about — against scratch PostgreSQL databases (`sp0_*`, `fk_probe_sp0`), never against `agentic_rag` or `agentic_rag_test`. One finding — the missing `GRANT` on the new `sessions` table — was fixed while this verification was still in flight, so its skeptics read the corrected text and refuted it. The defect was real when raised; the refutation is an artifact of that race, and the fix stands on its own.
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

### Decision 7 — `chat_history` leaves the SQL tool's allowlist (approved)

`backend/config.py:27` reads `sql_tool_allowed_tables: list[str] = ["chat_history", "documents"]`, and the SQL tool is reachable from `POST /chat` by any authenticated user (`routers/chat.py:49-50` → `agent/registry.py:96-103`). Its validation (`tools/sql_tool.py`) constrains statement count, statement type, and table name, but carries **no user or session parameter**; `db/schema.sql:51` grants `rag_readonly` `SELECT` on `chat_history` with no row-level security; and `registry.py:96-103` returns rows to the model as `repr(rows)`.

Ownership of `chat_history` cannot be enforced while that entry exists. A user asks a question, the model emits a `sql_query` call, and every user's conversations come back verbatim. This needs no jailbreak: `backend/tests/test_e2e_matrix.py:135` records the model emitting `sql_query` for the plain prompt *"Berapa jumlah baris pada tabel chat_history?"* and passing.

Without Decision 7, SP0 fails its own goal — `GET /chat/history` would be locked while an equivalent read stays open through the agent. The cost is that the SQL tool can no longer answer questions about conversation history. That capability is at odds with making conversations private, so the loss is intended rather than tolerated. `documents` stays: the corpus is deliberately shared (Decision 3).

**The change is three files, not one.** `config.py:27` is only a default; `backend/.env:20` and `backend/.env.example:20` both override it with `SQL_TOOL_ALLOWED_TABLES=["chat_history","documents"]`, and `config.py:34` sets `env_file=".env"`. Editing `config.py` alone changes nothing at runtime.

Rejected: **row-level security scoped per user** — it preserves the capability, but needs an RLS policy, a per-request `app.current_user_id` plumbed through a SQLAlchemy connection event, and `FORCE ROW LEVEL SECURITY` (or a separate role), because RLS does not apply to a table's owner. That is a sub-project of its own, for a capability SP0 is deliberately giving up.

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

-- Required. `GRANT ... ON ALL TABLES IN SCHEMA public` (db/schema.sql:44) was evaluated
-- when schema.sql ran and covers only the tables that existed then, so it does not reach
-- this new table. Without this line POST /chat dies with
-- `permission denied for table sessions`, because the application connects as rag_app.
GRANT SELECT, INSERT, UPDATE, DELETE ON sessions TO rag_app;

-- Refuse to guess, but only when there is something to guess about. Counting the pending
-- work keeps this a true no-op on a second run even after a second account exists, and it
-- catches the reverse case -- rows needing attribution with no user to attribute them to --
-- that a bare `n > 1` test waves through into a NOT NULL violation.
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

Notes:

- **Idempotent by construction.** `IF NOT EXISTS` on every object, a `NOT EXISTS` guard on the backfill insert and the constraint, and the `documents` update is self-limiting because the second run matches zero rows.
- **`title` is nullable and stays null after backfill.** SP1's list endpoint falls back to the first user message when `title IS NULL`. Deriving titles during backfill would be speculative work for a rendering detail SP1 owns.
- **`ON DELETE CASCADE` on `sessions.user_id`** — deleting a user removes their conversations, which cascades to `chat_history` through the new foreign key. This is intended: conversations are private.
- **`ON DELETE SET NULL` on `documents.user_id`** — the corpus is shared, so removing a user must not destroy knowledge other users rely on. The uploader becomes unknown rather than the documents becoming garbage.
- **`rag_readonly` deliberately gets no access to `sessions`.** `db/schema.sql:50-51` is an allowlist — `REVOKE ALL ON ALL TABLES` then `GRANT SELECT ON chat_history, documents` — so the new table is excluded. That is the desired outcome: `sessions` carries conversation metadata, and §18 of the project spec treats everything the SQL tool can reach as LLM-visible. It is called out here because it is currently an incidental consequence of statement ordering rather than a stated decision, and a future reader could "fix" it by adding `sessions` to line 51.
- **Adding `documents.user_id` makes uploader attribution readable by every user.** `documents` stays in `sql_tool_allowed_tables`, and `agent/registry.py:96-103` hands rows back to the model as `repr(rows)`, so a user can ask the assistant who uploaded a given document and receive the numeric `user_id`. This is accepted rather than overlooked: the corpus is shared by Decision 3, so that person could already read the document's *content* — what is newly disclosed is attribution alone. `users` is not allowlisted, so the id cannot be resolved to a username by the same route. If attribution ever needs to be private, the fix is a column allowlist in `tools/sql_tool.py`, not removing `documents`, which would cost the tool its only remaining purpose.
- **The guard tests pending work, not the user count alone.** A bare `n > 1` test would abort the second run on any database that has since gained a second account, even with nothing left to attribute — so "no-op on a second run" would quietly stop being true. It would also wave through the opposite case, rows needing attribution with zero users, and die on the `NOT NULL` constraint instead of refusing clearly. Checking both numbers closes both directions. It is the one place where guessing could silently attribute one person's conversations to another, and on this machine it cannot fire, which is exactly why it costs nothing to keep.
- **`get_or_create_session` flushes explicitly, and the flush is load-bearing rather than stylistic.** `chat()` adds the `ChatHistory` row and calls a single `db.flush()`, so both INSERTs are pending in one unit of work. SQLAlchemy does **not** order them by the foreign key. Every edge in its topological sort comes from a `relationship()`; these models declare only a raw FK column, so the unit of work falls back to `Mapper._sort_key` (`sqlalchemy/orm/mapper.py:727`), which is `module.ClassName`. `models.ChatHistory` therefore sorts before `models.ChatSession`, the `chat_history` INSERT is emitted first, and the FK rejects it: `IntegrityError: insert or update on table "chat_history" violates foreign key constraint "chat_history_session_fk"`. `get_db` then rolls back, so the `sessions` row never persists and **every** message on that session id keeps failing, not just the first. An explicit `db.flush()` — or declaring a `relationship()` — fixes it. The flush is one line and costs one round trip on the first message of a session.
  This was reproduced on PostgreSQL 17 with the migration's exact DDL, in both directions: without the flush the flush fails as above; with it, and with a `relationship()` added instead, both succeed.

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
        db.flush()  # the chat_history FK needs this row present before its own INSERT is ordered
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

### `backend/services/document_service.py`, `backend/routers/documents.py`, `backend/routers/upload.py`

`ingest_file(db, path)` at `document_service.py:54` gains a `user_id: int` parameter, passed through to the `Document(...)` construction at line 65. It has **three** call sites — two production, one test — and all three must be updated:

- `backend/routers/documents.py:30` — the `POST /documents` route.
- `backend/routers/upload.py:30` — inside the `if kind == "document":` branch of `POST /upload`. That route already has `user` from `Depends(get_current_user)` at line 19, so no new dependency is needed.
- `backend/tests/test_document_service.py:56` — `document_service.ingest_file(db, target)`. A test call site, but it breaks the same way and counts toward §11 criterion 3.

Missing the second one fails late and loudly rather than at review time: `upload.py:29-34` catches only `IngestError` and `EmbeddingError`, and `backend/main.py` registers no global exception handler, so the `TypeError` from the missing argument escapes as a 500. This is a live path — `frontend/src/components/UploadButton.vue:33` accepts `.png,.jpg,.jpeg,.webp,.pdf,.txt,.md` and sends the document kinds to `POST /upload` (`frontend/src/services/api.ts:112`).

### `backend/config.py`, `backend/.env`, `backend/.env.example`

`sql_tool_allowed_tables` becomes `["documents"]` in all three. `config.py:27` holds the default and `backend/.env:20` / `backend/.env.example:20` hold the override that actually wins — see Decision 7.

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
| `POST` | `/upload` | document-kind uploads now record the uploader |

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
| `test_upload_records_uploader` | A `.md` file sent through `POST /upload` — the path most uploads actually take — persists `user_id` on the ingested `documents` rows. Testing `POST /documents` alone would miss the call site that was missing from the first draft. The `user_id` passed must be a real `users.id`: `documents.user_id` carries a foreign key, so a fabricated value fails on the constraint rather than on the assertion. |
| existing suites | `test_chat_endpoint.py` and `test_auth.py` must pass **unmodified**. |
| `test_models.py`, `test_document_service.py` | must pass after the minimal edits below — *incidental* breakage. |
| `test_e2e_matrix.py` | must pass after its SQL-over-`chat_history` case is rewritten — *deliberate* breakage, Decision 7. |
| `test_sql_tool_cannot_reach_chat_history` | **new** — `chat_history` is rejected even when the model asks for it (Decision 7). |

The first three rows are load-bearing, and the claim is deliberately narrower than in this spec's first draft. Two kinds of test edit are expected, and conflating them is what the first draft got wrong.

**Incidental breakage.** `backend/tests/test_models.py:16-21` performs `db.add(ChatHistory(session_id="test-session", role="user", message="halo"))` followed by `db.flush()`, with no `sessions` row. The new foreign key rejects it: `ERROR: insert or update on table "chat_history" violates foreign key constraint "chat_history_session_fk"`. Separately, `backend/tests/test_document_service.py:56` calls `ingest_file(db, target)` and breaks on the new required parameter. Each fix is one line, and each is correct rather than regrettable — those tests were asserting against a schema that permitted orphan rows, and removing that permission is the point of the sub-project.

**Deliberate breakage.** `backend/tests/test_e2e_matrix.py:135` currently proves the SQL tool *can* query `chat_history`. Decision 7 reverses that, so the case must be rewritten to assert the tool refuses. This is a behaviour change under test on purpose, not a regression.

The tripwire concerns the **upsert design (Decision 6)** and nothing else. If `test_chat_endpoint.py` needs editing, or if a chat case in `test_e2e_matrix.py` breaks for a reason unrelated to Decision 7, then Decision 6 is wrong and should be revisited before proceeding. Changes in `test_models.py`, `test_document_service.py`, and the SQL-tool case say nothing about Decision 6. An earlier draft of this section did not draw that distinction and would have sent an implementer to dismantle the wrong decision.

Frontend: `frontend/src/composables/__tests__/useChat.spec.ts` must still pass. Add a case covering `fetchMe()` populating `username` from the server response.

---

## 9. Invariants and risks

- **A `sessions` row must exist before any `chat_history` row.** The foreign key enforces this; `get_or_create_session` satisfies it. `routers/chat.py` is the only **production** writer of `chat_history`, but it is not the only writer: `backend/tests/test_models.py:16` inserts directly through the ORM with no parent session and must be updated (§8). Recorded as a comment in `models.py` because the next writer will otherwise learn this from a constraint violation.
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

1. `db/migrations/001_ownership.sql` applies cleanly to `agentic_rag`, is a no-op on a second run, and `POST /chat` then succeeds **as `rag_app`** — applying cleanly is not the same as the application role being able to write the new table.
2. `agentic_rag_test` carries the same schema.
3. The full backend suite passes, with `test_chat_endpoint.py` and `test_auth.py` unmodified and the three expected edits from §8 in place.
4. A two-user isolation check returns 404 for the foreign session, both for `GET /chat/history` and `POST /chat`.
5. The agent refuses to read another user's conversations by **any** route. Concretely: a user asks the assistant to query `chat_history` through the SQL tool and is refused, not answered. This is the counterpart to criterion 4 — the endpoint check alone passed on the first draft of this spec, while the SQL tool stayed wide open (Decision 7).
6. `GET /auth/me` returns `username`, `role`, and `created_at`.
7. `npm run build` succeeds and all six existing components render unchanged in light and dark mode.
8. `docs/DONE.md` gains rows recording both the isolation result and the SQL-tool refusal.
