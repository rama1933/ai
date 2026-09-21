# Definition of Done — verification log

Run date: 2026-09-21 (refresh)

Every row below was filled by running the command during this refresh and pasting what it
printed. Nothing is ticked from memory, from the plan text, or from a previous run of this
document. Where a row did not behave as the plan expected, the row says so.

Verdicts: **PASS** (the command ran and the requirement holds) · **FAIL** (the command ran and
the requirement does not hold) · **UNVERIFIED** (no command could prove it on this machine).
Where a row holds only under a stated scope limit, the limit is written into the row.

## Verdict summary — all 21 rows

| # | Section | Requirement | Verdict |
|---|---|---|---|
| 1 | Backend | FastAPI berjalan | **PASS** |
| 2 | Backend | PostgreSQL terhubung | **PASS** |
| 3 | Backend | pgvector aktif | **PASS** |
| 4 | Backend | Ollama berjalan | **PASS** |
| 5 | Backend | RAG berhasil | **PASS** |
| 6 | Backend | OCR berhasil | **PASS** |
| 7 | Backend | SQL Tool berhasil | **PASS** |
| 8 | Backend | Agent dapat memilih tool | **PASS** |
| 9 | Frontend | Chat UI berjalan | **PASS** |
| 10 | Frontend | Kirim pertanyaan | **PASS** |
| 11 | Frontend | Upload gambar | **PASS** |
| 12 | Frontend | Upload dokumen | **PASS** |
| 13 | Frontend | Response AI tampil | **PASS** (scope: served modules + a direct render, no browser) |
| 14 | Frontend | Loading state | **PASS** (scope: served module + a direct render, no browser) |
| 15 | Frontend | Error handling | **FAIL** — 500, not the specified 503 |
| 16 | Security | Authentication | **PASS** |
| 17 | Security | Authorization | **PASS** |
| 18 | Security | File validation | **PASS** |
| 19 | Security | SQL restriction | **PASS** |
| 20 | Security | Prompt injection mitigation | **PASS** |
| 21 | Security | `.env` tidak masuk Git | **PASS** |

No row is UNVERIFIED.

This refresh supersedes the previous revision of this file, which recorded rows 8 and 20 as FAIL
and rows 6, 11 and 12 as flaky. Those verdicts are now stale: the routing work in commit
`4b67f1e` (`fix: tighten agent routing rules for small talk`) changed the observed behaviour, and
the reruns below show the three flaky rows passing cleanly. The one row that did **not** change is
row 15, which still fails.

## Environment notes for this run

- `python` and `python3` are shadowed on this machine, so the plan's `python scripts/check_infra.py`
  was run as `/opt/homebrew/bin/python3.10 scripts/check_infra.py`.
- `psql` is keg-only; run as `/opt/homebrew/opt/postgresql@17/bin/psql`.
- The plan's backend row is `curl -s localhost:8000/health`. Port 8000 was already held by a
  leftover `uvicorn` process that predates this run (`lsof` → pid 99692), and port 5173 by a
  leftover `node`/vite process (pid 99835). Rather than reuse a server of unknown provenance, this
  run started its own: backend on **:8040**, vite dev server on **:5175** (5173 and 5174 were taken,
  so Vite auto-incremented). Both leftovers are still running and were left alone.
- The Frontend section's manual rows were exercised with `curl` against that fresh pair (no browser
  was opened), so each row records what curl could observe.
- The servers this run started (a fake-Ollama on :8012, backends on :8031/:8033/:8040, vite on
  :5175) were stopped after the checks.

## Backend

| Requirement | Verified by | Result |
|---|---|---|
| FastAPI berjalan | `curl -s localhost:8040/health` | **PASS** — `{"status":"ok"}` |
| PostgreSQL terhubung | `../.venv/bin/pytest tests/test_models.py -q` | **PASS** — `3 passed, 1 warning in 0.63s` |
| pgvector aktif | `psql -d agentic_rag -c "\d documents"` shows `vector(768)` | **PASS** — `embedding \| vector(768)`, plus index `"documents_embedding_idx" hnsw (embedding vector_cosine_ops)` |
| Ollama berjalan | `/opt/homebrew/bin/python3.10 scripts/check_infra.py` | **PASS** — `OK  postgres+pgvector, schema, ollama models all reachable` (exit 0) |
| RAG berhasil | `../.venv/bin/pytest tests/test_e2e_matrix.py::test_rag_001_document_question_uses_rag` | **PASS** — passed in every clean matrix run (12 of 12) and every clean full-suite run (4 of 4) |
| OCR berhasil | `../.venv/bin/pytest tests/test_e2e_matrix.py::test_ocr_001_image_question_uses_ocr` | **PASS** — passed in every clean matrix run (12 of 12) and every clean full-suite run (4 of 4). The previous revision of this file recorded this row as flaky; it no longer reproduces |
| SQL Tool berhasil | `../.venv/bin/pytest tests/test_e2e_matrix.py::test_sql_001_statistics_question_uses_sql` | **PASS** — passed in every clean matrix run (12 of 12) and every clean full-suite run (4 of 4) |
| Agent dapat memilih tool | `../.venv/bin/pytest tests/test_e2e_matrix.py -k "agent_00"` | **PASS** — both `test_agent_001_general_question_answers_without_tool` and `test_agent_002_ambiguous_question_picks_a_tool` PASSED in every clean matrix run (12 of 12). This row was FAIL in the previous revision |

## Frontend

| Requirement | Verified by | Result |
|---|---|---|
| Chat UI berjalan | `npm run dev`, open :5173 | **PASS** — `GET :5175/ -> HTTP 200 bytes=428`, body carries `<div id="app"></div>` and `<script type="module" src="/src/main.ts">`. The module graph compiles and is served: `GET /src/main.ts -> HTTP 200 bytes=578`, `GET /src/App.vue -> HTTP 200 bytes=2740` |
| Kirim pertanyaan | live curl: send a message, read the reply | **PASS** — `POST /auth/register -> HTTP 201`; `POST /auth/login -> HTTP 200`; `POST /chat -> HTTP 200` with `{"answer":"Karyawan tetap berhak atas cuti tahunan sebanyak 12 hari kerja per tahun.","tool_used":"rag_search","sources":[...]}`. The turn round-trips and is persisted: `GET /chat/history?session_id=dod-rag -> HTTP 200` replaying `[{"role":"user",...},{"role":"assistant",...}]` |
| Upload gambar | live curl: upload the receipt, ask for the total | **PASS** — `POST /upload -> HTTP 200 {"filename":"143f2a71...-receipt.png","status":"stored","kind":"image"}`; the follow-up `"Berapa total transaksi pada struk ini?"` returned `{"answer":"Total transaksi pada struk tersebut adalah Rp 43.000.","tool_used":"image_ocr","sources":[{"filename":"143f2a71...-receipt.png","score":null}]}`. The figure printed on the fixture receipt (`43000`) is read correctly. The previous revision recorded this row as flaky (2 of 4 sends); it did not reproduce here |
| Upload dokumen | live curl: upload a document, ask a question about it | **PASS** — `POST /upload -> HTTP 200 {"filename":"bf9676ef...-policy.txt","status":"processed","kind":"document"}` for the `policy.txt` fixture; the follow-up `"Menurut dokumen kebijakan, berapa hari cuti tahunan karyawan tetap?"` returned `tool_used=rag_search` with four `sources` entries and the answer `"...12 hari kerja per tahun."`. The previous revision recorded a 2-of-3 flake here; it did not reproduce (5 consecutive live sends of the policy question all returned `rag_search` with clean prose). Note: the fixture set still has no PDF (`.txt` and `.png` only), so the *PDF* path was not exercised |
| Response AI tampil | served renderer module + a direct render | **PASS** — `GET :5175/src/components/MessageBubble.vue -> HTTP 200 bytes=7617` contains `markdown-it`, `DOMPurify` and `linkify`. Rendering executed directly with the app's own configuration (`new MarkdownIt({ linkify: true, breaks: true })` over `**Kebijakan cuti**\n\n- 12 hari kerja\n- lihat [panduan](https://example.com)`) produced `<p><strong>Kebijakan cuti</strong></p><ul><li>12 hari kerja</li><li>lihat <a href="https://example.com">panduan</a></li></ul>`. Scope limit: no browser was opened, so a pixel-level render of a live reply was not observed |
| Loading state | served module | **PASS** — `GET :5175/src/components/ChatBox.vue -> HTTP 200 bytes=12150` contains `Sedang berpikir` inside `<span class="inline-block animate-pulse">`; `useChat` sets `isLoading` around every request. Scope limit: the spinner's appearance during a live wait was not observed in a browser |
| Error handling | point the backend at a socket that refuses, send a message, expect 503 | **FAIL** — a refused connection yields **HTTP 500 `Internal Server Error`**, not the 503 `local LLM unavailable` the plan specifies. See Step 2 below |

## Security

| Requirement | Verified by | Result |
|---|---|---|
| Authentication | `../.venv/bin/pytest tests/test_auth.py -q` | **PASS** — `5 passed, 1 warning in 2.23s` |
| Authorization | `../.venv/bin/pytest tests/test_chat_endpoint.py::test_chat_requires_authentication -q` | **PASS** — `1 passed, 1 warning in 0.28s` |
| File validation | `../.venv/bin/pytest tests/test_upload_service.py -q` | **PASS** — `13 passed, 1 warning in 0.03s` (9 in the previous revision; the extra cases cover binary content masquerading as text, added by commit `a88038b`) |
| SQL restriction | `../.venv/bin/pytest tests/test_sql_tool.py -q` | **PASS** — `18 passed, 1 warning in 0.24s` (12 in the previous revision; the extra cases cover data-modifying CTEs, added by commit `463ff0e`) |
| Prompt injection mitigation | `../.venv/bin/pytest tests/test_e2e_matrix.py::test_sec_003_prompt_injection_in_a_document_is_ignored` | **PASS** — passed in every clean matrix run (12 of 12) and every clean full-suite run (4 of 4), i.e. 16 clean observations with zero failures. The previous revision recorded 4 failures in 5 standalone runs; that was under the pre-`4b67f1e` system prompt. Scope limit: this is a behavioural test of one planted instruction, not a proof that the mitigation is robust — see Known limitations |
| `.env` tidak masuk Git | `git check-ignore -v backend/.env` | **PASS** — `.gitignore:1:.env	backend/.env`; `git log --all --oneline -- backend/.env` printed nothing |

## Step 2: error handling, verified deliberately

Ollama itself was not stopped (other work depends on it). Instead two extra backends were started:
one pointed at a dead port, one pointed at a server that always answers 502.

```bash
# backend pointed at a dead port
cd backend && OLLAMA_BASE_URL=http://127.0.0.1:9 ../.venv/bin/uvicorn main:app --port 8031
# fake Ollama that always answers 502, plus a backend pointed at it
/opt/homebrew/bin/python3.10 /tmp/notollama.py            # serves 502 on :8012
cd backend && OLLAMA_BASE_URL=http://127.0.0.1:8012 ../.venv/bin/uvicorn main:app --port 8033
```

Observed, with a valid token:

| Backend points at | `POST /chat` | Body |
|---|---|---|
| `http://127.0.0.1:9` (nothing listening) | **HTTP 500** | `Internal Server Error` |
| `http://127.0.0.1:8012` (reachable, answers 502) | **HTTP 503** | `{"detail":"local LLM unavailable: ollama /api/chat returned 502: {\"error\":\"simulated ollama failure\"}"}` |

Server log for the dead-port case ends with:

```text
  File ".../backend/agent/orchestrator.py", line 121, in run_agent
    reply = _chat(messages)
  File ".../backend/agent/orchestrator.py", line 82, in _chat
    response = httpx.post(
  ...
httpx.ConnectError: [Errno 61] Connection refused
```

So the 503 handler is correct but incomplete: `_chat` converts a non-200 **response** into
`AgentError` (which `routers/chat.py:51-52` turns into 503), but a connection failure raises
`httpx.ConnectError`, which nothing catches, so FastAPI returns 500. That is exactly the case this
step was written to exercise — "stop Ollama" produces an unreachable socket, not a 502 — so the
frontend's red bar receives an `Internal Server Error` rather than `local LLM unavailable`. The
red bar itself is wired (`ChatBox.vue` contains `bg-red-50`; `useChat` sets `error` from any thrown
api error), so the defect is the status code and the message, not the UI branch. The environment was
not modified: `.env` was left untouched and `OLLAMA_BASE_URL` was overridden per process only.

## Step 3: no secret ever entered the repo

```text
$ git check-ignore -v backend/.env
.gitignore:1:.env	backend/.env

$ git log --all --oneline -- backend/.env
(no output)

$ grep -rn "rag_app_pw\|rag_readonly_pw" --include="*.py" --include="*.ts" --include="*.vue" .
backend/tests/conftest.py:11:os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://rag_app:rag_app_pw@localhost:5432/agentic_rag_test")
backend/tests/conftest.py:12:os.environ.setdefault("DATABASE_URL_READONLY", "postgresql+psycopg2://rag_readonly:rag_readonly_pw@localhost:5432/agentic_rag_test")
```

**PASS.** The only source-level matches are in `backend/tests/conftest.py`, in the test-only
credentials for the throwaway `agentic_rag_test` database. No router, service, tool, agent module,
component, or `api.ts` contains them.

## Step 4: full suite

```text
$ cd backend && ../.venv/bin/pytest tests/ -q
91 passed, 1 warning in 38.66s          # run B
91 passed, 1 warning in 39.77s          # run C
91 passed, 1 warning in 40.52s          # run D
91 passed, 1 warning in 38.04s          # run E

$ cd ../frontend && npm run test
 Test Files  1 passed (1)
      Tests  5 passed (5)
   Duration  1.17s

$ npm run build
dist/index.html                   0.47 kB │ gzip:  0.30 kB
dist/assets/index-BvDFcfQk.css    7.59 kB │ gzip:  2.41 kB
dist/assets/index-CvZRmka1.js   247.55 kB │ gzip: 98.06 kB
✓ built in 692ms
```

`pytest tests/ --collect-only -q` reports **91 tests collected**, so 91 collected == 91 passed,
zero skipped. The single warning is a `starlette/anyio` `DeprecationWarning`, not a failure.

**PASS, with one caveat that is explained rather than hidden.** A fifth full-suite run taken during
this refresh printed `2 failed, 89 passed, 1 warning in 36.57s`. That run was **contaminated**:
a second pytest process was running against the same `agentic_rag_test` database at the same time.
The failure was reproduced deliberately and traced to a test-isolation defect, not to the
application — see failure note 2. When the suite is the only pytest process touching that database,
it is 91 passed, four times out of four.

## Failure notes

1. **Frontend / Error handling — an unreachable Ollama returns 500, not 503.** `httpx.ConnectError`
   is raised out of `_chat` and caught by nothing, so FastAPI's default handler answers 500
   `Internal Server Error`. The plan's Step 2 ("stop Ollama → expect the red error bar with 503") is
   therefore not met. This is the only failing row in the table. It is unchanged from the previous
   revision of this document: none of the commits after `d8f8447` touched this path.
2. **A test-isolation defect that only bites when two pytest processes share the test database.**
   `backend/tests/test_auth.py:14-20` has an `autouse` fixture that runs after *every* test in that
   module and deletes **every** row matching `users.username LIKE 'user-%'`. The e2e matrix's
   module-scoped `auth` fixture (`tests/test_e2e_matrix.py:83`) names its user `user-<hex8>` — the
   same namespace. When `test_auth.py` runs while `test_e2e_matrix.py` is running against the same
   `agentic_rag_test` database, the matrix's user is deleted underneath it, `get_current_user`
   (`backend/security.py:51-53`) finds no such row, and every authenticated matrix call is answered
   `401 {"detail":"unknown user"}`.
   - Reproduced deliberately: with the matrix running in one process and `test_auth.py` looping in
     another, the matrix ended `8 failed, 1 passed, 1 warning in 1.70s`, with `assert 401 == 200`
     and `AssertionError: {"detail":"unknown user"}` on the authenticated tests, and
     `test_chat_history_is_persisted` failing `TypeError: string indices must be integers` at
     `tests/test_e2e_matrix.py:224` (a 401 body is a dict, so iterating it yields keys).
   - Identical signature to the contaminated full-suite run: `2 failed, 89 passed`, the same
     `{"detail":"unknown user"}` assertion and the same `TypeError`.
   - Sequential execution is safe because pytest collects `test_auth.py` before
     `test_e2e_matrix.py`, so the deletion happens before the matrix creates its user. The suite is
     simply not safe to run as two concurrent processes, nor under `pytest-xdist`.
   - Not fixed here: the assignment scoped this change to `docs/DONE.md`. It is recorded so the
     next person does not mistake a concurrent run's output for a product regression.
3. **Previously reported failure: "a malformed tool call can be returned verbatim as the answer."**
   Now fixed and re-verified. `agent/orchestrator.py` salvages a JSON tool-call blob emitted as
   content (`_salvage_tool_call`), and if it cannot, re-prompts (`_looks_like_tool_call` →
   `JSON_RETRY_PROMPT`) instead of handing the blob to the user. Live: 5 consecutive sends of the
   policy question all returned clean prose with `tool_used=rag_search`; no `{"name": ...}` blob was
   observed on any of them.
4. **Previously reported failures in `sec_002` and `agent_001`.** The assertions were rewritten by
   commit `051f75b` to measure behaviour rather than phrasing (`_signals_not_found`,
   `_fabricated_numbers`), and the system prompt was rewritten by `4b67f1e`. Both now pass in every
   clean run. Live confirmation for `agent_001`: `"Halo, perkenalkan dirimu dalam satu kalimat."`
   returned `{"answer":"Saya adalah asisten yang ramah dan siap membantu Anda dengan segala
   pertanyaan dan kebutuhan Anda.","tool_used":null,"sources":[]}` — no tool, clean prose.

## Known limitations

- **The model is small.** `llama3.2:3b` is a 3-billion-parameter model. Its tool routing and its
  answer synthesis are both weaker than an 8B model's would be, and the routing work in `4b67f1e`
  is a prompt-level fix to one 3B model's confusions, not a general routing guarantee. `llama3.1:8b`
  routes better but its ~4.9 GB of weights do not fit on this machine alongside the rest of the
  stack (see the plan's Known ceilings).
- **Prompt-injection defence is not enforced sanitisation.** It is two things: wrapping retrieved
  document text in `UNTRUSTED_DATA` delimiters, and a system-prompt rule telling the model to treat
  that block as data. Nothing strips or neutralises instructions inside a document. With a 3B model
  this is a soft mitigation; `sec_003` passing 16 of 16 clean runs shows it works on the one
  planted instruction the suite tests, not that it resists injection generally.
- **A connection failure to Ollama is a 500, not a 503** (failure note 1). The 503 path exists and
  works, but only for a reachable Ollama that answers non-200.
- **The suite cannot be run concurrently against one database** (failure note 2).
- **The SQL tool's regex guard is a fast rejection, not the security boundary.** The real boundary
  is the `rag_readonly` role's grants. The regex has already needed two rounds of tightening
  (data-modifying CTEs in `463ff0e`).
- **Retrieval and context handling are MVP-grade.** `chunk_text` is a fixed character window, so
  chunks can split mid-sentence; the agent has no streaming, so the UI waits for the whole answer;
  conversation history is the last 10 turns, unsummarized, so long sessions will eventually fill the
  context window.
- **The development database `agentic_rag` is not a clean fixture.** It carries rows left by this
  and earlier verification runs (users `dod_*`, `dodlive_*`, documents and uploads named
  `bf9676ef…-policy.txt`, `143f2a71…-receipt.png`, older `policy17.txt` / `a312959c…` rows, 60
  `chat_history` rows). The RAG row above is real but its `sources` list includes those older
  documents. The suite's own database `agentic_rag_test` is the one that matters and it is cleaned
  by the fixtures.
- **Two rows are verified without a browser.** "Response AI tampil" and "Loading state" were checked
  through the served modules and a direct render with the app's own markdown configuration, not by
  opening a browser and watching a live reply render.

## Conclusion

The plan's Step 4 expectation, "everything green," is **met under normal (single-process)
execution**: the backend is **91 passed**, the frontend suite is 5 passed, and the production build
succeeds. Of the 21 checklist rows, **19 are clean PASS**, **2 are PASS under the stated scope limit**
("Response AI tampil" and "Loading state" were not observed in a browser), and **1 is outright FAIL**:

- **Frontend / Error handling** — a stopped or unreachable Ollama yields HTTP 500
  `Internal Server Error` rather than the specified 503 `local LLM unavailable`, because
  `httpx.ConnectError` is uncaught.

No row is UNVERIFIED. Nothing in this document was ticked from the plan's wording or from the
previous revision of this file; every quoted string above is copied from a command that was run
during this refresh.
