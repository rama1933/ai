# SP1 — Standard Chat WebUI Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give this app the feature floor every modern chat WebUI stands on — many conversations you can start, name, revisit and delete; files you can attach, see, and still see after a reload; answers that stream and can be stopped; turns that can be copied, regenerated and edited. Nothing beyond that floor, and nothing that changes the agent, the retrieval pipeline, or the security boundaries SP0 established.

**Architecture:** The tool loop stays as it is. `run_agent` is refactored into a generator, `stream_agent`, that yields typed events; the existing `run_agent` becomes a four-line consumer of it, so `POST /chat` and every test that calls it keep working untouched. A new `POST /chat/stream` returns SSE over the same generator. The `sessions` table already carries `user_id`, `title` and `updated_at` with the right index — SP0 built it and nothing reads it yet — so multi-conversation is a CRUD router plus a sidebar, not a migration. Attachments stop being a single transient `image_path` on the request and become a JSONB column on the message that owns them, which is what makes them survive a reload. Regenerate and edit are one mechanism: the stream request may carry `truncate_after_id`.

**Tech Stack:** Python 3.10, FastAPI 0.115.6, SQLAlchemy 2.0 (sync), PostgreSQL 17 + pgvector, httpx, pytest; Vue 3 + TypeScript + Vite + Tailwind 3.4, Vitest.

**Precursor:** `docs/superpowers/plans/2026-09-21-sp0-ownership-foundation.md` (done), `docs/DONE.md`.

## Global Constraints

- Python interpreter is `/opt/homebrew/bin/python3.10`. Bare `python3` is shadowed by a shell function on this machine and is broken. Tests run as `../.venv/bin/pytest` from `backend/`.
- `psql` and `createdb` are keg-only: `/opt/homebrew/opt/postgresql@17/bin/psql`, or put that directory on `PATH` first.
- **Exactly one migration in this plan** — `db/migrations/003_message_attachments.sql`, Task 4, a single additive `ALTER TABLE ... ADD COLUMN ... DEFAULT`. Any task that thinks it needs a second one is wrong: re-read `db/schema.sql` first. `agentic_rag` holds the only real data; `agentic_rag_test` is disposable.
- Ownership failures return **404**, never 403, on every new endpoint. A 403 confirms the resource exists, which is the fact being protected. Route every `session_id` through `require_owned_session` / `get_or_create_session`; no new endpoint may query `ChatSession` by id directly.
- `sessions` and `chat_history` stay outside the `rag_readonly` grant, and so does the new column. Nothing in this plan edits the GRANT block in `db/schema.sql`.
- **The model never chooses a file.** Today `_resolve_image` resolves the path server-side from the authenticated request, and `image_ocr` takes no path argument. Task 4 makes attachments plural; that property must survive it exactly. A tool schema that grows a filename parameter is a defect, not a feature.
- The Vue app and its folder layout stay. No framework swap, no component library that owns the markup, no Tailwind v4.
- Code, identifiers, commit messages and comments in English. Conventional Commits (`feat:`, `fix:`, `test:`, `chore:`, `docs:`).
- Every task ends with a green test run and a commit. No task is done on a passing import alone.
- **Nothing in this plan may change the application's design.** See the next section; it is binding, not advisory.

---

## Conformance with the design document

The reference design is `docs/spec/agentic-rag-spec.md`, which is byte-identical to
`https://github.com/wisnu45/ai-engineer/blob/main/README.md` (verified 2026-09-22, 24,648 bytes, 1,146 lines).
Everything in SP1 is **additive**: it fills gaps the spec left open, and changes nothing the spec fixed.

### The four rules

1. **Additive only.** No field, column, endpoint, response key or directory that the spec names may be renamed, retyped, removed, or given a different meaning. New things sit beside them.
2. **The documented endpoints keep their documented shapes.** §20 pins `GET /health`, `POST /chat` and `POST /upload`. A request built exactly as §20 writes it must still succeed, and the response must still contain every key §20 shows. `POST /chat/stream` is an *additional* endpoint, not a replacement — Task 2 keeps `POST /chat` alive for exactly this reason.
3. **§15's chat column is preserved.** The mockup is a single column: header, scrolling message area, composer with the 📎 control and Send. Task 5 adds a sidebar *beside* that column; it may not restructure, reflow, or relocate anything inside it. At `< lg` the sidebar is a drawer and the mockup is what remains on screen.
4. **No new top-level directory, no new naming convention.** New files go into directories this repo already uses (`backend/routers/`, `frontend/src/composables/`, `frontend/src/components/`), following the names already there.

### Point-by-point check

| Spec | What it fixes | What SP1 does | Verdict |
|---|---|---|---|
| §4.1 Frontend | ViteJS · Vue · TailwindCSS · **Axios / Fetch API** · Markdown renderer | Unchanged. `streamMessage` uses `fetch`, which §4.1 names explicitly; `highlight.js` sits under the markdown renderer | **Conforms** |
| §4.3 Database | PostgreSQL · pgvector · chat history in PostgreSQL | Unchanged | **Conforms** |
| §6 Project Structure | `frontend/src/{components,services}`, `backend/{tools,services}`, `storage/uploads` | Two files into the existing `backend/routers/`, three into existing `frontend/src/{composables,components}`. No new top-level directory | **Conforms** (rule 4) |
| §7.1 `chat_history` | `id`, `session_id`, `role`, `message`, `created_at`; roles user/assistant/system/tool | All five columns keep their names and types. Adds `attachments JSONB DEFAULT '[]'`. Role set untouched | **Conforms** (rule 1) |
| §7.2 `documents` | `id`, `filename`, `content`, `embedding`, `metadata`, `created_at` | Not touched by SP1 | **Conforms** |
| §8 Agent Tools | Three tools: `rag_search`, `image_ocr`, `sql_query` | Still exactly three. `image_ocr` keeps zero parameters; it processes more attachments, it does not gain a way to name one | **Conforms** |
| §15 Fitur UI | Chat interface · message bubble · text input · file upload · loading · markdown · error handling · chat history · sources — "Frontend **minimal** memiliki" | All nine kept and working. SP1 adds above that floor, which the word *minimal* sanctions | **Conforms** (rule 3 guards the mockup) |
| §20 `POST /chat` | request `{session_id, message}` → response `{answer, tool_used, sources[].filename}` | Endpoint and both shapes unchanged. `attachments` is an optional added request field; the response is untouched | **Conforms** (rule 2) |
| §20 `POST /upload` | form-data `file` → `{filename, status}` | Both keys stay, same meaning. Adds `stored_name`, `display_name`, `mime`, `size` | **Conforms** (rule 1) |
| §25 Future Development | lists streaming response, conversation memory, citation/source tracking, user-specific KB, RBAC | SP1 implements streaming and conversation memory. The spec anticipated both | **Conforms** |

### Pre-existing deviations SP1 neither causes nor repairs

Recorded so no reviewer attributes them to this plan, and no task "fixes" them as a drive-by:

- §4.2 names **LangChain** as the agent framework and **PaddleOCR** for OCR. This repo uses Ollama's native tool calling and RapidOCR. Decided before SP1.
- §6 sketches `backend/agent.py` as one file and React-style `.jsx` components. The repo has a `backend/agent/` package, a `backend/routers/` layer, and Vue SFCs with `composables/`. Decided before SP1.
- §7.1 shows `session_id` with no foreign key. SP0 introduced the `sessions` table and the FK to give every row an owner — the one deliberate, documented departure, and the reason multi-conversation costs no migration here.
- §7.2 names the column `metadata`; the repo uses `doc_metadata` because `metadata` is reserved on a SQLAlchemy declarative class.
- §21–§22 Docker and §23's later roadmap rows remain unbuilt.

### Task 10 gate

The sweep does not pass on green tests alone. It must also record:

- [ ] A `POST /chat` request whose body is *literally* §20's `{"session_id": "session-001", "message": "..."}` — no `attachments` key — succeeding, with the response containing `answer`, `tool_used` and `sources[].filename`. Paste the actual response.
- [ ] A `POST /upload` response still carrying `filename` and `status`. Paste it.
- [ ] A screenshot at `< lg` showing §15's chat column intact with the sidebar closed.

---

## Dependency decisions — the ladder check

Recorded here so no task re-litigates them mid-implementation.

| Candidate | Verdict | Why |
|---|---|---|
| **`@vueuse/core` 14.4.0** | **Use it** | Already hoisted in `node_modules`, pulled in by `reka-ui`. Zero new install. Add it to `package.json` as `^14.1.0` anyway — depending on another package's transitive dep is how a silent break happens — and pin to 14, not 15, or npm installs a second tree. |
| **`reka-ui` 2.10.5** | **Use it** | Already a direct dependency and currently imported by nothing. Its `DropdownMenu`, `Dialog` and `AlertDialog` bring focus trapping, `aria-*` wiring and Esc handling that Tasks 5 and 7 would otherwise hand-write badly. |
| **`highlight.js`** | **Add** (Task 9) | The only new package in this plan. Cannot be done in a few lines or by something installed. Core build + explicit language registration only. |
| **`@ai-sdk/vue` 4.0.107** | **Rejected** | Peer-compatible (`vue ^3.3.4`) and its `useChat` really does cover streaming, `stop()`, `regenerate()` and message editing. But it dictates the wire format (the UI Message Stream protocol, which has no official Python helper — FastAPI would have to match the spec by hand, and a wrong field fails opaquely) and the message model (`UIMessage` + typed `parts`, forcing a rewrite of `MessageBubble.vue`). It replaces roughly 80 lines of `fetch` + `ReadableStream`. Not a trade worth making here. Revisit if a second provider or client ever appears. |
| **Open WebUI, Chainlit, Deep Chat** | **Rejected** | Each owns the interface. Keeping this Vue app and its design system was the explicit constraint. (For the record: `open-webui` 0.11.3 also requires Python ≥3.11, and this machine has 3.9/3.10/3.14 only.) |
| **`@nuxt/ui` 4** | **Rejected** | Requires Tailwind v4; this app is on 3.4. |

---

## File Structure

```text
ai/
├── db/
│   ├── schema.sql                              # MODIFY: chat_history.attachments          (Task 4)
│   └── migrations/003_message_attachments.sql  # CREATE                                    (Task 4)
│
├── backend/
│   ├── models.py                               # MODIFY: ChatHistory.attachments           (Task 4)
│   ├── schemas.py                              # MODIFY: HistoryItem, StreamChatRequest, SessionSummary, AttachmentRef
│   ├── agent/orchestrator.py                   # MODIFY: stream_agent() generator          (Task 1)
│   ├── agent/registry.py                       # MODIFY: image_ocr over every attached image (Task 4)
│   ├── routers/
│   │   ├── chat.py                             # MODIFY: /chat/stream, attachments, history ids
│   │   ├── sessions.py                         # CREATE: list / create / rename / delete   (Task 3)
│   │   ├── upload.py                           # MODIFY: richer UploadResponse             (Task 4)
│   │   └── attachments.py                      # CREATE: owner-scoped file serving         (Task 4)
│   ├── main.py                                 # MODIFY: include the two new routers
│   └── tests/
│       ├── test_orchestrator.py                # MODIFY: stream_agent event sequences
│       ├── test_chat_stream.py                 # CREATE
│       ├── test_sessions.py                    # CREATE
│       └── test_attachments.py                 # CREATE
│
└── frontend/
    ├── package.json                            # MODIFY: @vueuse/core (Task 5), highlight.js (Task 9)
    └── src/
        ├── services/api.ts                     # MODIFY: streamMessage, sessions, attachments
        ├── composables/
        │   ├── useChat.ts                      # MODIFY: streaming, stop, attachments, regenerate, edit
        │   ├── useSessions.ts                  # CREATE                                    (Task 5)
        │   └── useAttachments.ts               # CREATE: pending list + authed blob URLs    (Task 7)
        ├── components/
        │   ├── ChatBox.vue                     # MODIFY: sidebar, stop, composer, drop zone
        │   ├── SessionSidebar.vue              # CREATE                                    (Task 5)
        │   ├── AttachmentChip.vue              # CREATE                                    (Task 7)
        │   ├── MessageBubble.vue               # MODIFY: attachments + hover actions
        │   └── MessageActions.vue              # CREATE                                    (Task 8)
        └── lib/markdown.ts                     # CREATE: shared md-it + DOMPurify + hljs    (Task 9)
```

---

# Backend

## Task 1 — `stream_agent`: the tool loop becomes a generator

**Files:** `backend/agent/orchestrator.py`, `backend/tests/test_orchestrator.py`

Everything streaming rests on this and none of it is user-visible. Get the event contract right before an endpoint or a component exists.

### Design

`stream_agent(db, message, history, image_paths)` yields dicts. Four event types, no others:

```python
{"type": "tool",    "name": "rag_search"}
{"type": "sources", "sources": [SourceRef, ...]}
{"type": "delta",   "text": "Berdasar"}
{"type": "done",    "answer": "<full text>", "tool_used": "rag_search" | None, "sources": [...]}
```

`run_agent` becomes: drain the generator, return `AgentResult` from the `done` event. Its signature, return type and `AgentError` do not change, so `POST /chat` and the existing `test_orchestrator.py` cases are untouched.

**The JSON-leak guard.** `llama3.2:3b` intermittently writes a tool call as JSON prose into `message.content` — that is exactly what `_salvage_tool_call` exists for. Streaming that would flash a raw `{"name": ...}` blob at the user before the loop recognised it. The guard is cheap: buffer deltas until the first non-whitespace character is known. If it is `{`, keep buffering the whole turn and decide with the existing `_salvage_tool_call` / `_looks_like_tool_call` helpers when the turn ends. Otherwise emit freely from that point. Do not write a second JSON detector — reuse the two helpers already in the file.

### Steps

- [ ] Add `_chat_stream(messages) -> Iterator[dict]`: same POST as `_chat` but `"stream": True`, sent with `httpx.stream(...)`. Ollama answers NDJSON, one JSON object per line; yield each line's `message` dict. Same `httpx.HTTPError → AgentError` translation as `_chat`, and a non-200 must be read and raised before any line is yielded.
- [ ] Add `_accumulate(chunks)`: fold the chunk stream into `(content, tool_calls)` while yielding delta text, applying the JSON-leak guard. Tool-call chunks contribute no delta.
- [ ] Move `run_agent`'s loop body into `stream_agent`, preserving every existing behaviour: `agent_max_iterations`, `JSON_RETRY_PROMPT` on a malformed blob, `_salvage_tool_call` rebuilding a native call, `tool_used` frozen at the agent's first choice, `GIVE_UP_ANSWER` on exhaustion.
- [ ] Emit `tool` before `registry.dispatch` runs and `sources` after it, the latter only when `outcome.sources` is non-empty.
- [ ] Reduce `run_agent` to a consumer returning the `done` payload as `AgentResult`.
- [ ] Rename the `image_path` parameter to `image_paths: list[str]` threading through to `registry.dispatch`. Task 4 gives it more than one element; here it is a list of zero or one and nothing else changes.

### Verification

- [ ] Existing `test_orchestrator.py` cases pass unmodified. Add: a plain answer yields deltas then `done`; a tool turn yields `tool` → `sources` → deltas → `done`; a turn whose content is a `{"name": ...}` blob yields **no** delta before the salvage and the rebuilt call is dispatched; an exhausted loop yields `done` with `GIVE_UP_ANSWER`.
- [ ] Mock Ollama at the `httpx` layer with a real NDJSON body, not by monkeypatching `_chat_stream` — the line splitting is part of what is under test.
- [ ] `cd backend && ../.venv/bin/pytest tests/test_orchestrator.py -v`
- [ ] `cd backend && ../.venv/bin/pytest tests/ -m "not integration"`
- [ ] Commit: `refactor: turn the agent loop into a streaming generator`

---

## Task 2 — `POST /chat/stream`

**Files:** `backend/routers/chat.py`, `backend/schemas.py`, `backend/tests/test_chat_stream.py`

### Design

SSE, `media_type="text/event-stream"`, each frame a `data: {json}\n\n` line carrying a Task 1 event verbatim, plus one transport-only type:

```python
{"type": "error", "detail": "local LLM unavailable: ..."}
```

`AgentError` cannot become a 503 once the response has started, so it is delivered as an `error` event and the stream ends. The client shows it in the same banner a 503 uses today.

**The DB-session trap — read this before writing the endpoint.** FastAPI ≥ 0.106 exits `yield` dependencies *before* a `StreamingResponse` body is sent. `Depends(get_db)` is therefore already closed when the generator runs, and every ORM call inside it fails. The generator must open its own `SessionLocal()` and close it in a `finally`. Keep `Depends(get_db)` for the pre-stream work only — ownership, truncation, persisting the user row — and commit that before returning the response.

**Disconnect persistence.** Wrap the generator in `try/finally`. On `GeneratorExit` — the user pressed Stop — write the accumulated text as the assistant row and commit. A stopped answer that vanishes on reload is worse than a truncated one that stays.

### Steps

- [ ] `schemas.py`: `StreamChatRequest(ChatRequest)` with `truncate_after_id: int | None = None`; add `id: int` to `HistoryItem`.
- [ ] Extract the shared preamble of `chat()` — attachment resolution, `get_or_create_session`, the `HISTORY_TURNS` window, the user-row insert — into `_prepare_turn(db, payload, user)` and have both endpoints call it. No second copy of that logic.
- [ ] Truncation: when `truncate_after_id` is set, delete this session's `chat_history` rows with `id > truncate_after_id` **before** the history window is read. Scope the delete by `session_id` as well as id — an id alone is a cross-session write.
- [ ] Persist the assistant row inside the generator's `finally`, on the generator's own session, keyed on the `session_id` captured before the response started.
- [ ] Leave `POST /chat` in place. It is what the non-streaming tests exercise and it now costs four lines.

### Verification

- [ ] `test_chat_stream.py`: a happy turn produces deltas then exactly one `done`; a tool turn emits `tool` and `sources` before the first delta; an `AgentError` produces `error` and no `done`; `truncate_after_id` removes only that session's trailing rows; another user's session answers 404 before any byte is written.
- [ ] One test must assert the assistant row exists in `chat_history` after the stream closes. That is the DB-session trap's regression guard and the single most likely thing to break.
- [ ] `cd backend && ../.venv/bin/pytest tests/test_chat_stream.py tests/test_chat_endpoint.py tests/test_ownership.py -v`
- [ ] Commit: `feat: stream chat responses over SSE`

---

## Task 3 — Sessions CRUD

**Files:** `backend/routers/sessions.py` (new), `backend/schemas.py`, `backend/main.py`, `backend/tests/test_sessions.py`

| Method | Path | Purpose |
|---|---|---|
| GET | `/sessions` | the caller's conversations, newest activity first |
| POST | `/sessions` | create an empty conversation, server-generated id |
| PATCH | `/sessions/{id}` | rename |
| DELETE | `/sessions/{id}` | delete; `chat_history` follows by cascade |

### Steps

- [ ] `SessionSummary(id, title, created_at, updated_at)`; `SessionPatch(title: str = Field(min_length=1, max_length=200))`.
- [ ] `GET /sessions`: filter by `user_id`, `ORDER BY updated_at DESC`, `LIMIT 200`. `sessions_user_idx` already covers exactly this. No pagination — 200 conversations is well past the point where a sidebar stops being the right surface.
- [ ] `POST /sessions`: id is `f"session-{uuid4()}"`, generated **server-side**. The client stops inventing ids.
- [ ] `PATCH` and `DELETE` both begin with `require_owned_session`.
- [ ] Auto-title: in `_prepare_turn`, when `title` is `None`, set it to the first user message trimmed to 60 characters on a word boundary. `# ponytail: truncation, not an LLM-written title. Swap in a one-shot generate call if the titles read badly.`
- [ ] Register the router in `main.py`.

### Verification

- [ ] `test_sessions.py`: list returns only the caller's rows, in `updated_at DESC`; create returns an id that `GET /chat/history` then accepts; rename persists; delete cascades `chat_history` to zero rows; PATCH, DELETE and GET-history against another user's session each return **404, not 403**.
- [ ] `cd backend && ../.venv/bin/pytest tests/test_sessions.py tests/test_ownership.py -v`
- [ ] Commit: `feat: add session CRUD endpoints`

---

## Task 4 — Attachments become part of the message

**Files:** `db/migrations/003_message_attachments.sql` (new), `db/schema.sql`, `backend/models.py`, `backend/schemas.py`, `backend/routers/upload.py`, `backend/routers/attachments.py` (new), `backend/routers/chat.py`, `backend/agent/registry.py`, `backend/tests/test_attachments.py`

This is the task the current app is furthest from. Today a chat request carries one `image_path`, `chat_history` stores text only, and `UploadResponse.filename` returns the stored name — the uuid-prefixed one from `save_upload`, not what the user called the file. So: one file per message, the original name is lost, and the attachment disappears on reload.

### Design

Storage is a JSONB column on `chat_history`, **not** a new table. An attachment is never read except alongside the message that owns it, deletion already cascades through the session, and a join buys nothing. One additive `ALTER TABLE`:

```sql
ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb;
```

`rag_readonly` has no grant on `chat_history`, so the column is out of the SQL tool's reach for free. Do not touch the GRANT block.

**The client sends stored names and nothing else.** No display name, no MIME, no kind — the server re-derives all of it from the file on disk, exactly as `classify()` already does at upload time. Trusting client metadata here would let a caller mislabel a PDF as an image and pick which branch of the OCR path runs.

**Serving files back.** `GET /attachments/{stored_name}` requires the caller to own a session holding a message that references that name. An upload that was never sent is unreachable — deliberate, and the reason the composer previews from a local `URL.createObjectURL` instead of a round trip.

### Steps

- [ ] Migration `003_message_attachments.sql` with the `ALTER TABLE` above, and the same column added to `db/schema.sql` so a fresh database matches. Apply to `agentic_rag` and `agentic_rag_test`.
- [ ] `models.py`: `ChatHistory.attachments: Mapped[list] = mapped_column(JSONB, default=list)`.
- [ ] `schemas.py`: `AttachmentRef(stored_name, display_name, kind, mime, size)` for responses; requests carry `attachments: list[str]` (stored names) capped at 5 and replacing `image_path` entirely. Update `HistoryItem` to return `list[AttachmentRef]`.
- [ ] `upload.py`: `UploadResponse` gains `stored_name`, `display_name`, `mime`, `size`. `display_name` is `stored.name` with the `{uuid}-` prefix stripped; `stored_name` is the full name. Keep the existing document-ingest branch untouched — a `.pdf` still lands in the knowledge base as it does today, and now also comes back as a chip.
- [ ] `chat.py`: `_resolve_image` becomes `_resolve_attachments(names) -> list[ResolvedAttachment]`, applying the same `Path(name).name` + `is_relative_to(upload_dir)` + `is_file()` guard **per item**, and re-classifying each from disk. Store the resolved metadata on the user's `chat_history` row.
- [ ] `registry.py`: `image_ocr` runs over **every** attached image, concatenating results under `[display_name]` headers inside one `_wrap()`. The tool schema keeps zero parameters — the model must not gain a way to name a file. Non-image attachments are ignored by this tool; documents already reached the agent through `rag_search`.
- [ ] `attachments.py`: `GET /attachments/{stored_name}` — `get_current_user`, re-apply the path guard, then confirm a `chat_history` row referencing that name exists in a session owned by the caller. 404 on every failure, never 403. Return `FileResponse` with `Content-Disposition` carrying the display name and an explicit `Content-Type` from the stored MIME.
- [ ] Register the router in `main.py`.

### Verification

- [ ] `test_attachments.py`: a message round-trips its attachments through `GET /chat/history`; two images on one message are both OCR'd and both appear in the answer's sources; a stored name from another user's conversation returns **404**; `../` and an absolute path in `stored_name` are rejected; an upload that was never sent is not servable; more than 5 attachments is rejected at validation.
- [ ] `cd backend && ../.venv/bin/pytest tests/test_attachments.py tests/test_upload_endpoint.py tests/test_ocr_tool.py tests/test_registry.py -v`
- [ ] `cd backend && ../.venv/bin/pytest tests/ -m "not integration"`
- [ ] Commit: `feat: persist message attachments and serve them owner-scoped`

---

# Frontend

## Task 5 — Session sidebar

**Files:** `frontend/src/composables/useSessions.ts` (new), `frontend/src/components/SessionSidebar.vue` (new), `ChatBox.vue`, `useChat.ts`, `frontend/src/composables/__tests__/useSessions.spec.ts`

### Steps

- [ ] Add `@vueuse/core: ^14.1.0` to `package.json`. Confirm `npm ls @vueuse/core` reports **one** tree — a `^15` entry would duplicate it.
- [ ] `useSessions.ts`: module-level state (the singleton shape `useAuth` already uses) holding `sessions`, `activeId`, and `list/create/rename/remove/select`. `activeId` is a `useLocalStorage('agentic-rag-session', null)` ref — same key as today, so a returning user lands back in their last conversation.
- [ ] `useChat.ts`: `sessionId` stops being a module constant and becomes `useSessions().activeId`. Switching it reloads history and clears `input`, pending attachments and `error`.
- [ ] Migration for existing users, and it must be silent: that key already holds a bare id string from the current build. On first load, if `GET /sessions` is empty but a stored id is present, keep using it — `POST /chat` adopts it through `get_or_create_session`. No prompt, no lost conversation.
- [ ] `SessionSidebar.vue`: "Percakapan baru" button; list grouped into Hari ini / 7 hari terakhir / Lebih lama by `updated_at`; a client-side filter over titles; per-row rename and delete. `reka-ui` is a direct dependency nothing currently imports — this is where it starts paying for itself:
  - `DropdownMenu` for the per-row menu (keyboard navigation, `aria-*`, outside-click, free).
  - `AlertDialog` for delete confirmation. Never `window.confirm` — a native modal blocks the page and freezes browser tooling.
  - `Dialog` for the mobile drawer: focus trap, focus restore and `Esc` are already handled. Do not hand-write any of it.
- [ ] Responsive: a permanent rail ≥ `lg`, the `Dialog` drawer below it. Keep the composer's `max-w-3xl` column centred in the remaining space.
- [ ] Accessibility: the list is a `<nav>` with `aria-current="page"` on the active row. The rest comes from `reka-ui`.
- [ ] **Conformance rule 3 applies to this task above all others.** The sidebar wraps the existing layout; it does not reach inside it. `ChatBox.vue`'s header, message area and composer keep their current structure, classes and order — the only edit permitted there is the outer flex container and the drawer toggle button. If a step seems to require moving something inside the chat column, the step is wrong.

### Verification

- [ ] `useSessions.spec.ts`: create prepends and activates; rename updates in place; remove drops the row and, when it was active, activates the next one; a stored legacy id survives an empty list.
- [ ] `cd frontend && npm run test && npx vue-tsc -b`
- [ ] Manual, both themes at 375 and 1440: create → rename → switch → delete, with history correct after every step.
- [ ] Commit: `feat: add a conversation sidebar`

---

## Task 6 — Streaming transport and stop

**Files:** `frontend/src/services/api.ts`, `frontend/src/composables/useChat.ts`, `frontend/src/components/ChatBox.vue`, `frontend/src/composables/__tests__/useChat.spec.ts`

### Design

Axios cannot expose a streaming body in the browser, and `EventSource` cannot send a POST or an `Authorization` header. So `streamMessage` uses `fetch` + `ReadableStream` directly — the one place in the app that bypasses the axios instance, which means it must reproduce two things the interceptors do: attach the bearer token, and on 401 clear storage and reload. Export that 401 handling from `api.ts` as a named function and call it from both places rather than writing it twice.

SSE frames split on `\n\n`, and a chunk boundary can land mid-frame, so the reader keeps a carry buffer and parses only complete frames. Test that explicitly — it is the classic bug in a hand-rolled SSE client.

### Steps

- [ ] `api.ts`: the `StreamEvent` union mirroring Task 1's four types plus `error`; `streamMessage(body, signal)` as an async generator; `handleUnauthorized()` shared with the axios interceptor.
- [ ] `useChat.ts`: `send()` pushes an empty assistant message, sets `isStreaming`, appends each `delta` to `.content`, applies `tool`/`sources` to that same message, clears the flag on `done` or `error`. `isLoading` keeps its current meaning — request in flight, no token yet — so the typing-dots block does not change.
- [ ] `stop()` via `AbortController`, leaving the partial text in place; it is persisted server-side, so a reload must show the same thing.
- [ ] `ChatBox.vue`: the send button becomes a stop button while `isStreaming`; `Esc` calls `stop()` through `useEventListener`.
- [ ] Scroll-to-bottom pill driven by `useScroll(scrollRef)`. Delete the hand-written `isNearBottom` helper and its `watch`; the existing behaviour becomes `arrivedState.bottom || isStreaming`.
- [ ] While in the file: swap the raw `matchMedia('(prefers-reduced-motion: reduce)')` for `useMediaQuery` and the manual textarea-height `watch` for `useTextareaAutosize`. Pure deletions, same behaviour. Do them here or not at all — not as a drive-by later.

### Verification

- [ ] `useChat.spec.ts`: deltas accumulate onto one assistant message, not several; a frame split across two chunks parses once and correctly; `stop()` aborts and keeps the partial text; an `error` event lands in `error.value` and clears `isStreaming`.
- [ ] `cd frontend && npm run test && npx vue-tsc -b`
- [ ] Commit: `feat: stream assistant replies in the UI`

---

## Task 7 — Attachment UI

**Files:** `frontend/src/composables/useAttachments.ts` (new), `frontend/src/components/AttachmentChip.vue` (new), `ChatBox.vue`, `MessageBubble.vue`, `UploadButton.vue`, `api.ts`

### Design

`pendingImage: string | null` becomes `pending: Attachment[]`. Three ways in, because a chat UI without all three feels broken: the existing button, drag-and-drop onto the composer, and paste from the clipboard.

**Thumbnails need a blob URL, not a plain `src`.** `GET /attachments/{name}` requires a bearer token and `<img src>` cannot carry one. So `useAttachments` fetches with the token and hands back an object URL, revoking it on unmount. Resist the temptation to invent a signed-URL scheme for this: it is eight lines, and a second auth path is a second thing to get wrong.

### Steps

- [ ] `useAttachments.ts`: `pending` list, `add(files)` uploading each through `POST /upload` in sequence, `remove(storedName)`, `clear()`, and `objectUrl(storedName)` with a small cache plus `revokeObjectURL` on unmount.
- [ ] Composer previews come from the local `File` via `URL.createObjectURL` — no server round trip before the message is sent.
- [ ] `AttachmentChip.vue`: thumbnail for images, file glyph plus extension for documents, display name truncated in the middle (`laporan-…-2026.pdf` reads better than a cut-off head), size, and a remove button while pending.
- [ ] `ChatBox.vue`: a drop zone over the composer with a visible drag-over state, `@paste` pulling images off `event.clipboardData.files`, chips in a wrapping row above the textarea. Send is blocked while any upload is in flight.
- [ ] `MessageBubble.vue`: render a message's attachments above its text — images as thumbnails that open full size in a `reka-ui` `Dialog`, documents as chips linking to the download.
- [ ] Per-file errors are per-chip, not a global banner: one rejected `.exe` among four files must not discard the other three. The existing `describeError` already produces the right text for a 400.
- [ ] Keep the existing "document ingested into the knowledge base" assistant note — it is the only signal that a PDF did something beyond attaching.

### Verification

- [ ] Vitest: `add()` with three files produces three chips; a rejected file leaves the other chips intact and marks only its own; `remove()` drops one; `clear()` runs on session switch; object URLs are revoked on unmount.
- [ ] `cd frontend && npm run test && npx vue-tsc -b`
- [ ] Manual, and this is the acceptance test for the whole task: attach two images plus a PDF, send, ask about the images, **reload the page**, and confirm the chips and thumbnails are still on the message.
- [ ] Commit: `feat: attach multiple files and show them in history`

---

## Task 8 — Message actions: copy, regenerate, edit

**Files:** `frontend/src/components/MessageActions.vue` (new), `MessageBubble.vue`, `useChat.ts`, `api.ts`

### Steps

- [ ] `HistoryItem.id` and the stream's turn ids flow into `ChatMessage.id` so an action knows what to truncate from. Optimistic messages carry `id: null` and keep their actions disabled until the turn completes.
- [ ] `MessageActions.vue`: a row appearing on hover **and** on keyboard focus (`focus-within` — hover-only is unreachable by touch and by keyboard). Assistant: Salin, Regenerasi. User: Salin, Edit.
- [ ] Copy uses `useClipboard({ copiedDuring: 1500 })`, binding the "Tersalin" state to its `copied` ref. No hand-rolled `setTimeout`, no `execCommand` fallback — localhost, modern browser.
- [ ] `regenerate()`: `truncate_after_id` = the id of the user message preceding the assistant one, text = that same user message, attachments = that message's stored names. Drop the assistant message locally, stream into a fresh one.
- [ ] `edit()`: the bubble becomes a textarea seeded with the current text; saving sends `truncate_after_id` = the id of the row **before** the edited one, with the new text and the original attachments. Cancel restores. Everything after the edited turn disappears — that is this milestone's semantics, and the sidebar row's `updated_at` moves with it. (Claude keeps both versions behind `‹ 2/3 ›` arrows instead; see **Deferred**.)
- [ ] Both actions refuse to run while `isStreaming`.

### Verification

- [ ] `useChat.spec.ts`: regenerate sends the right `truncate_after_id` and replaces exactly one assistant message; edit truncates the tail and re-sends with attachments preserved; both are no-ops mid-stream.
- [ ] `cd frontend && npm run test && npx vue-tsc -b`
- [ ] Manual: edit a middle message, reload, and confirm the server's history matches what the UI showed.
- [ ] Commit: `feat: add copy, regenerate and edit message actions`

---

## Task 9 — Code blocks and one shared markdown renderer

**Files:** `frontend/src/lib/markdown.ts` (new), `MessageBubble.vue`, `frontend/package.json`

### Ladder check before installing

Highlighting is the only rung of this task that justifies a new package: CSS cannot tokenise source code, and hand-writing a tokeniser for the languages this assistant emits is a week of work with a worse result. `highlight.js` core plus an explicit language list is ~40 KB gzipped. Import `highlight.js/lib/core` and register only `json`, `sql`, `python`, `bash`, `typescript`, `xml` — never the barrel import, which pulls 190 languages.

### Steps

- [ ] `npm i highlight.js`.
- [ ] `lib/markdown.ts`: one `MarkdownIt` instance with the `highlight` hook and one `DOMPurify.sanitize` wrapper, exported as `renderMarkdown(src: string): string`. `MessageBubble.vue` imports it instead of building its own — the sanitiser config must exist once, in one file.
- [ ] The sanitiser allow-list must permit `class` on `code`/`span`, or every highlight is stripped. Prove that in a test, not by eye.
- [ ] Per-block toolbar: language label and a copy button, by wrapping each `<pre>` at render time.
- [ ] Streaming safety: partial markdown is re-parsed on every delta. Coalesce with `refThrottled(content, 80)` rather than a hand-written rAF batcher, and let an unclosed fence render as plain text until it closes.

### Verification

- [ ] Vitest: a fenced block survives sanitising with its `hljs-*` classes intact, and a `<script>` in model output does not.
- [ ] `cd frontend && npm run test && npx vue-tsc -b && npm run build` — the build is what proves the tree-shaken language set. Record the bundle-size delta in the commit message.
- [ ] Commit: `feat: highlight code blocks and share one markdown renderer`

---

## Task 10 — Documentation and verification sweep

**Files:** `README.md`, `docs/DONE.md`

- [ ] README: add `/chat/stream`, the four `/sessions` rows and `/attachments/{stored_name}` to the API table; move "streaming responses" out of **Not built**; note migration 003 in Setup.
- [ ] `docs/DONE.md`: append an SP1 section in the existing format — one row per feature, every verdict pasted from a command actually run during the sweep. No row ticked from this plan's text.
- [ ] Full suite both sides: `cd backend && ../.venv/bin/pytest tests/ -v`; `cd frontend && npm run test && npm run build`.
- [ ] Commit: `docs: record the SP1 chat WebUI baseline`

---

## Deferred — and what pulls each one in

The baseline above is what a standard AI WebUI has. These are the rungs above it.

| Deferred | Add it when |
|---|---|
| **Edit as branching** (`‹ 2/3 ›` version arrows) | Someone loses work to the destructive edit in Task 8. Needs `chat_history.parent_id` and a tree walk — a migration and a real design, not a tweak. |
| **Search across message text** | The title filter in Task 6 stops finding things. Postgres FTS on `chat_history.message`, one GIN index. |
| **Expandable tool steps** | The tool badge stops being enough explanation. The data already flows through Task 1's events; this is UI only. |
| **LLM-written conversation titles** | The 60-character truncation reads badly in the sidebar. One extra `generate` call. |
| **Export / share a conversation** | Someone asks for it. Markdown dump of `GET /chat/history`. |
| **Command palette (⌘K)** | There are more than ~10 keyboard-reachable actions. Below that a palette is decoration. |
| Model picker | A second model is pulled and someone wants to switch. |
| Custom instructions per user | A second real user exists with different needs. |
| Projects — scoped knowledge base and instructions | The shared corpus starts returning the wrong documents. The corpus is deliberately shared today (SP0 Decision). |
| Hybrid BM25 + reranking, query rewriting | Answers are wrong because retrieval missed, not because the model reasoned badly. Measure first. |
| Artifacts / canvas, code execution, web search, MCP client | Each is its own plan and its own security review. None belong in a baseline. |
| Vision input (images the model sees directly) | A vision model replaces `llama3.2:3b`. Until then OCR is the image path, and no UI change can fake it. |
| Observability, evaluation pipeline, RBAC admin UI | Before this leaves localhost, not while it is a single-user local app. |
