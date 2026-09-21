# Agentic RAG — Local AI System

Local Agentic RAG assistant: FastAPI + PostgreSQL/pgvector + RapidOCR + Ollama + Vue 3.
The LLM picks between three tools — document search, image OCR, and read-only SQL.

Spec: `docs/spec/agentic-rag-spec.md` · Plan: `docs/superpowers/plans/`

## Requirements

macOS with Homebrew. No Docker needed.

Disk: budget roughly **3 GB** for the Ollama models plus **~600 MB** for the Python
and Node dependencies. The rest of the stack is small, but models dominate — do not
start this on a volume with less than ~4 GB free.

## Setup

```bash
brew install postgresql@17 pgvector ollama
brew services start postgresql@17
brew services start ollama
ollama pull llama3.2:3b
ollama pull nomic-embed-text

# postgresql@17 is keg-only, so psql/createdb are NOT on PATH. Either add them:
#   export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
# or call every command below by absolute path, e.g.
#   /opt/homebrew/opt/postgresql@17/bin/createdb agentic_rag
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"

createdb agentic_rag && createdb agentic_rag_test
psql -d postgres -c "CREATE ROLE rag_app LOGIN PASSWORD 'rag_app_pw';"
psql -d postgres -c "CREATE ROLE rag_readonly LOGIN PASSWORD 'rag_readonly_pw';"
psql -d agentic_rag -f db/schema.sql
psql -d agentic_rag_test -f db/schema.sql

/opt/homebrew/bin/python3.10 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cp backend/.env.example backend/.env   # then set JWT_SECRET

cd frontend && npm install && cd ..
```

Python dependencies come from `backend/requirements.txt` (pinned):

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
pydantic==2.10.4
pydantic-settings==2.7.0
sqlalchemy==2.0.36
psycopg2-binary==2.9.10
pgvector==0.3.6
httpx==0.28.1
pypdf==5.1.0
python-multipart==0.0.20
pyjwt==2.10.1
passlib[bcrypt]==1.7.4
bcrypt==4.0.1
pytest==8.3.4
rapidocr-onnxruntime==1.4.4
```

`bcrypt` is pinned to 4.0.1 on purpose: passlib 1.7.4 reads `bcrypt.__about__`,
which bcrypt 4.1+ removed, and the version probe failure is noisy.

## Run

```bash
./scripts/dev.sh      # backend :8000, frontend :5173
```

`dev.sh` runs `scripts/check_infra.py` first and refuses to start if Postgres,
pgvector, the schema, or the Ollama models are missing.

Open http://localhost:5173, register a user, and start chatting.

## Test

```bash
cd backend && ../.venv/bin/pytest tests/ -v          # includes live-model integration tests
cd backend && ../.venv/bin/pytest tests/ -m "not integration"   # fast, no Ollama needed
cd frontend && npm run test
```

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | no | liveness |
| POST | `/auth/register` | no | create a user |
| POST | `/auth/login` | no | obtain a JWT |
| POST | `/documents` | yes | ingest a document into the knowledge base |
| POST | `/upload` | yes | store an image, or store+ingest a document |
| POST | `/chat` | yes | ask the agent |
| GET | `/chat/history` | yes | replay a session |

## Security notes

- The SQL tool runs as `rag_readonly`, which holds `SELECT` on `documents` only — never on `users`, and no longer on `chat_history`, which was deliberately removed so the agent cannot read conversations.
- Uploads are checked by extension, MIME type, size, and magic bytes; the signature wins.
- Retrieved documents and OCR output are wrapped in `UNTRUSTED_DATA` markers and the system prompt forbids following instructions found inside them.
- The model never chooses which image to OCR; the path comes from the authenticated request.
- `backend/.env` is git-ignored. Set a real `JWT_SECRET` before this leaves localhost.

## Not built

Docker deployment, streaming responses, reranking, hybrid BM25, multi-agent supervisor.
See spec §25 for the roadmap beyond MVP.
