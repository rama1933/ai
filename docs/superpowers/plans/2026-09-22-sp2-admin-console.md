# SP2 — Admin Console: Knowledge Base, Activity Log, User Management

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the operator of this system the three screens it is missing — *what the assistant knows* (every ingested document and its chunks, with the ability to delete), *what has happened* (an activity log across auth, ingestion, chat turns and admin actions), and *who may use it* (user CRUD, roles, deactivation). Nothing beyond that, and nothing that changes the agent loop, the retrieval pipeline, or the security boundaries SP0/SP1 established.

**Architecture:** One new backend router, `backend/routers/admin.py`, mounted behind the `require_role("ADMIN")` dependency that already exists in `security.py` and has never been used. The knowledge-base screen needs no new storage: `documents` already holds one row per chunk with `filename`, `doc_metadata.chunk_index/chunk_count` and `user_id`, so a document is a `GROUP BY filename` and deleting one is a `DELETE ... WHERE filename = :name` plus unlinking the file in `upload_dir`. Only the log needs a table — `activity_log`, written through a single ~20-line helper called from the handful of places where something worth recording happens. User management is CRUD over the `users` table that already carries `role`, plus one new column, `is_active`, enforced in `get_current_user` so deactivation takes effect on the next request instead of when the JWT expires. On the frontend there is no router today and SP2 does not add one: `App.vue` grows a hash-driven view switch (`#/admin/knowledge`, `#/admin/logs`, `#/admin/users`) in ~15 lines, and the admin screens live beside `ChatBox`, not inside it. Navigation is an **Admin group in the existing conversation sidebar** — three rows in `SessionSidebarBody`, which the permanent rail and the mobile drawer already share, rendered only when the signed-in role is `ADMIN`.

**Tech Stack:** Python 3.10, FastAPI 0.115.6, SQLAlchemy 2.0 (sync), PostgreSQL 17 + pgvector, pytest; Vue 3 + TypeScript + Vite + Tailwind 3.4, reka-ui, @vueuse/core, Vitest. No new dependency in either half.

**Precursor:** `docs/superpowers/plans/2026-09-21-sp0-ownership-foundation.md` (done), `docs/superpowers/plans/2026-09-22-sp1-chat-ux-parity.md` (done), `docs/DONE.md`.

---

## Global Constraints

- Python interpreter is `/opt/homebrew/bin/python3.10`; bare `python3` is shadowed by a shell function on this machine. Tests run as `../.venv/bin/pytest` from `backend/`. Frontend tests run as `npm run test` from `frontend/`.
- `psql`/`createdb` are keg-only: `/opt/homebrew/opt/postgresql@17/bin/psql`, or put that directory on `PATH` first.
- **Exactly one migration in this plan** — `db/migrations/004_admin_console.sql`, Task 1. Any later task that thinks it needs a second one is wrong: re-read `db/schema.sql` first.
- **The `rag_readonly` grant does not change.** `activity_log` must never appear in it, and neither may `users`, `sessions` or `chat_history`. The SQL tool's reach is LLM-visible; the admin API is not. A task that adds a GRANT for the new table to `rag_readonly` is a defect. `rag_app` *does* need DML on it — the `GRANT ... ON ALL TABLES` in `schema.sql` runs at apply time, so the migration must grant explicitly.
- **403 for role failures, 404 for ownership failures.** `require_role` already answers 403 and that stays: an admin-only surface is not a secret, an individual session is. No admin endpoint may resolve a `session_id` outside `require_owned_session`.
- **The log records metadata, not conversation content.** `activity_log` stores action, actor, target and a small JSONB detail (tool used, duration, chunk count, message length). It does not store message text, and SP2 gives no admin any endpoint that reads another user's `chat_history`. That is a deliberate boundary, not an omission — see Decision 3.
- The Vue app and its folder layout stay: no vue-router, no framework swap, no component library that owns the markup, no Tailwind v4. New components go under `frontend/src/components/admin/`, which is a subdirectory of an existing directory, not a new top-level one.
- Every admin write is audited. An admin endpoint that mutates and logs nothing is incomplete.
- Code, identifiers, comments and commit messages in English. Conventional Commits (`feat:`, `fix:`, `test:`, `chore:`, `docs:`).
- Every task ends with a green test run and a commit. No task is done on a passing import alone.

## Conformance with the design document

`docs/spec/agentic-rag-spec.md` is the reference. SP2 is **additive**, under the same four rules SP1 adopted: nothing the spec names is renamed, retyped, removed or given a new meaning; `GET /health`, `POST /chat` and `POST /upload` keep their documented shapes; §15's chat column is untouched (the admin screens are a *different* screen, reachable only by an ADMIN, and the chat view renders exactly as it does today); no new top-level directory.

§25 "Future Development" lists **Role-based access control** and **Observability dan tracing**. SP2 implements the first properly (the roles existed, nothing enforced them beyond the token) and the first useful slice of the second. §5's `users.role` CHECK constraint keeps its three values — `ADMIN`, `USER`, `READ_ONLY` — and SP2 adds no fourth.

## Decisions

1. **A document is its `filename`.** `save_upload` prefixes every stored name with a `uuid4().hex-`, so `documents.filename` is already unique per upload and is a safe grouping key; `display_name_of()` renders it for humans. No `documents_id` table, no join table, no migration for the knowledge screen.
2. **Deactivate, don't delete.** Deleting a user cascades away their sessions and chat history and orphans their documents (`ON DELETE SET NULL`). `is_active = false` is the normal control; `DELETE /admin/users/{id}` stays available but is the sharp option, and both are audited.
3. **Admins read the log, not the conversations.** "Lihat semua history" in SP2 means every *event*: who signed in, who ingested what, which tool answered which turn and how long it took, what an admin changed. Message text stays owner-scoped exactly as SP0 left it. If reading other people's conversations is later wanted, it is its own plan with its own consent/retention decision — bolting it onto this one would quietly reverse SP0 Decision 7.
4. **Offset pagination, no cursor.** A local single-operator system will not have the row counts that make `LIMIT/OFFSET` hurt. `ponytail:` note the ceiling in the router; switch to keyset pagination if the log passes ~100k rows.
5. **No background job for ingestion in SP2.** Ingestion stays synchronous. The knowledge screen makes the current blocking behaviour *visible*, which is the prerequisite for fixing it; see "Suggested follow-ups" §1.
6. **The first ADMIN is promoted by hand.** `POST /auth/register` keeps creating `USER` and gains no role parameter — a public endpoint that can mint admins is a hole. Promotion is one documented SQL statement (Task 11); after that, admins create admins through `POST /admin/users`.

---

## Task 1 — Migration: `activity_log` and `users.is_active`

- [ ] Write `db/migrations/004_admin_console.sql`:
  - `ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;`
  - `CREATE TABLE IF NOT EXISTS activity_log (id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id) ON DELETE SET NULL, username VARCHAR(100), action VARCHAR(50) NOT NULL, target TEXT, detail JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);`
    `username` is a deliberate snapshot: a deleted user must still be legible in the log after the FK nulls out.
  - `CREATE INDEX IF NOT EXISTS activity_log_created_idx ON activity_log (created_at DESC);`
  - `CREATE INDEX IF NOT EXISTS activity_log_action_idx ON activity_log (action, created_at DESC);`
  - `GRANT SELECT, INSERT, UPDATE, DELETE ON activity_log TO rag_app; GRANT USAGE, SELECT ON SEQUENCE activity_log_id_seq TO rag_app;`
  - No grant of any kind to `rag_readonly`.
- [ ] Mirror the same objects into `db/schema.sql` so a fresh database matches a migrated one, keeping the GRANT block at the bottom and its warning comment intact.
- [ ] Apply to both databases: `psql -d agentic_rag -f db/migrations/004_admin_console.sql` and the same for `agentic_rag_test`.
- [ ] `backend/models.py`: add `User.is_active: Mapped[bool]` and an `ActivityLog` model matching the table.
- [ ] Tests (`backend/tests/test_activity_log.py`): an `ActivityLog` row round-trips; `rag_readonly` gets `permission denied` on `SELECT * FROM activity_log` (mirror the assertion style already in `test_sql_tool.py`).
- [ ] `../.venv/bin/pytest tests/ -m "not integration"` green → commit.

## Task 2 — Audit helper and its call sites

- [ ] `backend/services/audit.py`: one function, `record(db, action, user=None, target=None, **detail) -> None`, that adds an `ActivityLog` row (snapshotting `user.username`) and nothing else — no commit, no flush; it rides the request's unit of work like every other write in this codebase.
- [ ] Module-level action constants so call sites cannot typo a string: `AUTH_LOGIN`, `AUTH_LOGIN_FAILED`, `AUTH_REGISTER`, `DOC_INGEST`, `DOC_DELETE`, `UPLOAD_STORE`, `CHAT_TURN`, `SESSION_DELETE`, `ADMIN_USER_CREATE`, `ADMIN_USER_UPDATE`, `ADMIN_USER_DELETE`, `ADMIN_LOG_PURGE`.
- [ ] Wire the call sites:
  - `routers/auth.py` — login success (`user`), login failure (`user=None`, `detail={"username": ...}`), register.
  - `routers/documents.py` — ingest, `target=stored_path.name`, `detail={"chunks": n}`.
  - `routers/upload.py` — store, `target=stored_name`, `detail={"kind": ..., "size": ...}`.
  - `routers/chat.py` — one row per completed turn: `target=session_id`, `detail={"tool_used": ..., "duration_ms": ..., "chars_in": len(message), "chars_out": len(answer)}`. In the streaming path this belongs where the assistant row is persisted, on the same `SessionLocal` that writes it, so a dropped connection does not leave a half-turn logged.
  - `routers/sessions.py` — delete.
- [ ] A failed login is written on an unauthenticated endpoint, i.e. an unbounded row source. `ponytail:` note the ceiling in `audit.py` and point at the purge endpoint from Task 5 as the release valve.
- [ ] Tests (`backend/tests/test_audit.py`): a successful login writes exactly one `AUTH_LOGIN` row; a wrong password writes `AUTH_LOGIN_FAILED` with a null `user_id` and the attempted username; a chat turn writes `CHAT_TURN` carrying `tool_used`.
- [ ] Green → commit.

## Task 3 — Enforce `is_active`

- [ ] `security.get_current_user`: after the user is loaded, `if not user.is_active: raise HTTPException(401, "account disabled")`. Two lines; the row is already fetched on every request, so deactivation bites immediately rather than at token expiry.
- [ ] Test (`backend/tests/test_auth.py`): a valid token for a deactivated user gets 401 on a protected route, and `POST /auth/login` for that user also fails — check the login path explicitly, it does not go through `get_current_user`.
- [ ] Green → commit.

## Task 4 — Admin API: stats and knowledge base

- [ ] `backend/routers/admin.py`, `APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_role("ADMIN"))])` — the guard sits on the router, so no endpoint can be added without it.
- [ ] `GET /admin/stats` → `{users, active_users, documents, chunks, sessions, messages, storage_bytes}`. Cheap aggregate queries; `storage_bytes` sums the files in `upload_dir`.
- [ ] `GET /admin/documents?q=&limit=50&offset=0` → one row per `filename`: `filename`, `display_name`, `chunks`, `chars`, `owner` (username or null), `created_at`. Implemented as a `GROUP BY filename` with `MIN(created_at)`; `q` filters on `filename ILIKE`.
- [ ] `GET /admin/documents/{filename}/chunks?limit=20&offset=0` → `chunk_index`, `chars`, and `content` truncated to 500 characters. The path parameter is matched against the column, never joined into a path; the file is not opened here.
- [ ] `DELETE /admin/documents/{filename}` → deletes every chunk with that filename, unlinks `upload_dir/{Path(filename).name}` if it exists (resolve and assert it stays inside `upload_dir`, same guard `_resolve_attachments` uses), audits `DOC_DELETE` with the chunk count, returns 204. A filename with no rows is 404.
- [ ] Schemas in `schemas.py`: `AdminStats`, `KnowledgeItem`, `ChunkItem`.
- [ ] Tests (`backend/tests/test_admin_documents.py`): a `USER` token gets 403 on every route; an `ADMIN` sees one row per ingested file with the right chunk count; deleting removes the chunks, removes the file, and writes the audit row; a traversal attempt in `{filename}` (`../../etc/passwd`) deletes nothing and 404s.
- [ ] Green → commit.

## Task 5 — Admin API: activity log

- [ ] `GET /admin/logs?action=&username=&since=&until=&limit=100&offset=0` → newest first, each row `{id, username, action, target, detail, created_at}`. `ponytail:` comment naming the offset-pagination ceiling (Decision 4).
- [ ] `GET /admin/logs/actions` → the distinct action values present, so the frontend filter is populated from data rather than a hardcoded list.
- [ ] `DELETE /admin/logs?before=<ISO date>` → retention purge, audited as `ADMIN_LOG_PURGE` with the deleted count, returns `{deleted: n}`. `before` is required: no bare "delete the log".
- [ ] Tests (`backend/tests/test_admin_logs.py`): filtering by action and by username each narrow the result; purge deletes only rows older than `before` and leaves its own audit row behind; `USER` gets 403.
- [ ] Green → commit.

## Task 6 — Admin API: user management

- [ ] `GET /admin/users?q=&limit=100&offset=0` → `{id, username, role, is_active, created_at, sessions, documents}` (the last two are counts).
- [ ] `POST /admin/users` → `{username, password, role}`; reuses `LoginRequest`'s length rules via a new `AdminUserCreate` schema; 409 on a duplicate username; audited.
- [ ] `PATCH /admin/users/{id}` → any of `role`, `is_active`, `password`; audited with the changed field names only, never the password.
- [ ] `DELETE /admin/users/{id}` → 204, audited.
- [ ] Three guards, all enforced server-side and all tested:
  - An admin may not demote, deactivate or delete **themselves**.
  - No operation may leave the system with zero active `ADMIN` accounts.
  - `PATCH` of an unknown id is 404.
- [ ] Tests (`backend/tests/test_admin_users.py`): `USER` gets 403 everywhere; creating a user then logging in as them works; the last-admin guard rejects each of the three paths (demote, deactivate, delete); deactivating a user makes their existing token fail with 401 (this is Task 3's behaviour, asserted end-to-end here).
- [ ] Green → commit.

## Task 7 — Frontend: hash view switch and admin shell

- [ ] `frontend/src/composables/useView.ts`: a module-level `ref` seeded from `location.hash`, kept in sync with a `hashchange` listener, and a `go(view)` that writes the hash. Views: `chat`, `admin/knowledge`, `admin/logs`, `admin/users`. An unknown hash falls back to `chat`. `ponytail:` comment — this is a hash switch, not routing; introduce `vue-router` only when a screen needs path params or guards.
- [ ] `App.vue`: render `ChatBox` for `chat`, `AdminLayout` for anything under `admin/`, `LoginForm` when unauthenticated. A non-admin who types an admin hash lands back on `chat` — the 403 from the API is the boundary, this is just courtesy.
- [ ] `frontend/src/components/admin/AdminLayout.vue`: page header with the stats from `GET /admin/stats`, three tabs, a "Kembali ke chat" control, and a slot for the active view. Reuses the existing Tailwind tokens (`bg-bg`, `border-border`, `text-subtle`, …) so light and dark both work without new CSS.
- [ ] `services/api.ts`: the admin calls, typed, grouped under an `admin` object on the existing `api`.
- [ ] Tests (`frontend/src/composables/__tests__/useView.spec.ts`): the hash seeds the view, `go()` writes it, an unknown hash falls back, and `hashchange` from the back button updates it.
- [ ] `npm run test` green → commit.

## Task 7b — The admin menu in the sidebar

The console is worthless if nobody can find it, so it is reached from the conversation sidebar the person already has open — not from a hash they must type, and not from a control hidden in the header.

- [ ] `SessionSidebarBody.vue` grows a **footer block** below the conversation list (`nav`/empty-state stays `flex-1`, so the footer pins to the bottom): `border-t border-border`, `p-3`, `flex flex-col gap-0.5`. The body keeps owning no shell chrome — both the rail and the drawer get the menu for free because they share this component.
- [ ] The block renders only for an admin: `const { role } = useAuth()` in the body, `v-if="role === 'ADMIN'"`. A `USER` sees the sidebar exactly as it is today — no disabled rows, no greyed-out teaser. The API's 403 is the boundary; this is the reason not to advertise a door that will not open.
- [ ] Three items, an `AppIcon` plus a label each, styled like the existing session rows (`rounded-xl px-3 py-2 text-sm`, `text-subtle`, `hover:bg-elevated/60`) so the sidebar reads as one list:
  - `database` · **Data Training** → `admin/knowledge`
  - `history` · **Log Aktivitas** → `admin/logs`
  - `user` · **Pengguna** → `admin/users`
- [ ] Above them, a group heading in the same style the date groups use (`text-[11px] font-semibold uppercase tracking-wider text-faint`): **Admin**.
- [ ] Active state: the item matching the current view gets `bg-elevated text-fg`, its icon `text-primary`, and `aria-current="page"` — the same three signals an active conversation row already carries.
- [ ] Clicking an item calls `go(view)` and emits `navigate`, so the mobile drawer closes behind it exactly as selecting a conversation does.
- [ ] `AppIcon.vue`: add `database` and `history` to the `name` union and two inline `<template v-else-if>` paths beside the existing ones. `user` is already there and is reused — no third icon.
- [ ] The sidebar stays mounted on the admin screens: `AdminLayout` renders the same `SessionSidebar` rail and drawer that `ChatBox` does, so the menu is visible from inside the console and a conversation is always one click away. Selecting a conversation from there calls `go('chat')` before `select(id)`.
- [ ] Tests (`frontend/src/components/__tests__/SessionSidebarBody.spec.ts`): the three items render for an `ADMIN` and none of them for a `USER`; clicking **Data Training** sets the view to `admin/knowledge` and emits `navigate`; the item for the active view carries `aria-current="page"`.
- [ ] `npm run test` green → commit.

## Task 8 — Frontend: Knowledge view

- [ ] `components/admin/KnowledgeView.vue`: search box, the document table (display name, chunks, chars, owner, date), row expansion that fetches and shows that document's chunks, and pagination controls.
- [ ] Delete with a reka-ui `AlertDialog` confirmation — **not** `window.confirm`, which is a blocking browser modal.
- [ ] An upload control on this screen posting to the existing `POST /documents`, with the ingesting state visible and the table refreshed on success. Reuse `UploadButton.vue` if it fits without modification; if it does not, do not bend it — a plain file input here is less code than a prop matrix there.
- [ ] Empty state ("belum ada dokumen"), error state via the existing `describeError`.
- [ ] Test: the view renders rows from a mocked `api.admin.listDocuments` and calls `deleteDocument` after confirmation.
- [ ] Green → commit.

## Task 9 — Frontend: Logs view

- [ ] `components/admin/LogsView.vue`: filters (action select fed by `GET /admin/logs/actions`, username, date range), the table (time, user, action, target, detail), pagination.
- [ ] Detail renders as compact key/value pairs, not raw JSON.
- [ ] The purge control lives behind the same `AlertDialog` and requires a date.
- [ ] Test: filter changes refetch with the right params; rows render.
- [ ] Green → commit.

## Task 10 — Frontend: Users view

- [ ] `components/admin/UsersView.vue`: the user table, a create form (username, password, role), inline role change, an activate/deactivate toggle, and delete behind `AlertDialog`.
- [ ] The current admin's own row renders its destructive controls disabled with a title explaining why — the server guard is the boundary, this is the courtesy layer.
- [ ] Server errors (409 duplicate, 400 last-admin) surface through `describeError`, which needs a `409` case added to its switch.
- [ ] Test: creating a user calls the API and refreshes; the self-row's destructive controls are disabled.
- [ ] Green → commit.

## Task 11 — Docs and verification

- [ ] `README.md`: add the `/admin/*` rows to the API table; add the promotion statement under Setup —
      `psql -d agentic_rag -c "UPDATE users SET role='ADMIN' WHERE username='<you>';"` — and the 004 migration line beside the 003 one.
- [ ] `README.md` security notes: one line saying the admin console is role-gated, that `is_active` is enforced per request, and that the log holds metadata only.
- [ ] `docs/DONE.md`: new rows for the three features, each filled by running the command, not from memory.
- [ ] Screenshots of the three screens in light and dark into `docs/screenshots/` (`sp2-knowledge-*.png`, `sp2-logs-*.png`, `sp2-users-*.png`), plus `sp2-sidebar-admin.png` showing the Admin group in the sidebar and `sp2-sidebar-user.png` showing the same sidebar signed in as a `USER`, without it.
- [ ] Full runs: `cd backend && ../.venv/bin/pytest tests/ -v` and `cd frontend && npm run test`. Paste the counts into `DONE.md`.
- [ ] Commit.

---

## Suggested follow-ups (not in SP2)

Ranked by value per line of code, with the lazy version of each:

1. **Ingestion that does not block the request.** A 60-page PDF holds the HTTP connection through embedding today; the knowledge screen will make this obvious immediately. Lazy version: FastAPI `BackgroundTasks` plus a `status` column (`pending`/`ready`/`failed`) on a per-document row, with the knowledge table showing it. No Celery, no Redis.
2. **Retrieval playground.** An admin box that takes a question and shows the chunks `rag_search` would retrieve with their cosine scores. It is a thin wrapper over the existing `rag_tool` and it is the single best debugging tool for a RAG system — "kenapa jawabannya salah" becomes answerable in one screen.
3. **Answer feedback.** A 👍/👎 on each assistant message written into `activity_log` with the session and tool. Two endpoints and a column's worth of work; it turns the log into an evaluation dataset for the pipeline work in spec §25.
4. **Duplicate detection on ingest.** `sha256` of the file stored beside the chunks; re-uploading the same document warns instead of silently doubling the corpus and skewing retrieval. ~10 lines.
5. **Per-user knowledge scoping.** `documents.user_id` already records provenance and `document_service.ingest_file` says the filter is a one-line change. Spec §25 names it; it becomes worth doing the moment a second person uses the system.
6. **Runtime settings.** `agent_temperature`, `rag_min_score`, `ollama_llm_model` are `.env`-only, so tuning retrieval means restarting the backend. An admin settings screen over a small key/value table removes that loop.
7. **Health panel.** `/health` exists but reports liveness only. Extend it with the Ollama model list, the pgvector version and `storage/uploads` disk usage, and render it in the admin header — `scripts/check_infra.py` already knows how to ask all three.
8. **Self-service account.** Change password and sign out of all sessions, for the `USER` role. Small, and the absence is conspicuous once user management exists.
9. **Export.** Conversation to Markdown, log to CSV. Two endpoints, no new concepts.
10. **Rate limiting.** Per-user request ceilings computed from `activity_log`, once the log exists. Only worth it if this ever leaves localhost.
