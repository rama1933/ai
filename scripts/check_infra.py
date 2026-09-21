"""Verify every external dependency the backend assumes is live.

Run: /opt/homebrew/bin/python3.10 scripts/check_infra.py
Exits 0 when everything is reachable, 1 with a readable reason otherwise.
"""
import json
import shutil
import subprocess
import sys
import urllib.request

OLLAMA = "http://localhost:11434"
REQUIRED_MODELS = {"llama3.2:3b", "nomic-embed-text"}
DATABASES = ("agentic_rag", "agentic_rag_test")

# postgresql@17 is keg-only, so psql is not on PATH by default.
PSQL = shutil.which("psql") or "/opt/homebrew/opt/postgresql@17/bin/psql"

failures: list[str] = []


def psql(db: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run([PSQL, "-d", db, "-tAc", sql], capture_output=True, text=True)


def check_postgres() -> None:
    for db in DATABASES:
        out = psql(db, "SELECT extname FROM pg_extension WHERE extname = 'vector'")
        if out.returncode != 0:
            failures.append(f"postgres: cannot connect to {db}: {out.stderr.strip()}")
        elif out.stdout.strip() != "vector":
            failures.append(f"postgres: pgvector extension missing in {db}")


def check_tables() -> None:
    out = psql("agentic_rag", "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    if out.returncode != 0:
        return  # already reported by check_postgres
    missing = {"users", "chat_history", "sessions", "documents"} - set(out.stdout.split())
    if missing:
        failures.append(
            f"postgres: missing tables {sorted(missing)}; "
            "run db/schema.sql then db/migrations/001_ownership.sql"
        )
        return

    # SP0's migration adds documents.user_id. A database that never had it applied
    # passes the table check above -- every table it names already existed -- and then
    # dies on the first upload, so the column the migration adds is checked here too.
    cols = psql(
        "agentic_rag",
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'documents'",
    )
    if cols.returncode == 0 and "user_id" not in cols.stdout.split():
        failures.append(
            "postgres: documents has no user_id column; run db/migrations/001_ownership.sql"
        )


def check_ollama() -> None:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=5) as resp:
            names = {m["name"] for m in json.load(resp)["models"]}
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator verbatim
        failures.append(f"ollama: unreachable at {OLLAMA}: {exc}")
        return
    missing = {m for m in REQUIRED_MODELS if not any(n.startswith(m) for n in names)}
    if missing:
        failures.append(f"ollama: missing models {sorted(missing)}; run `ollama pull <model>`")


def main() -> int:
    check_postgres()
    check_tables()
    check_ollama()
    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        return 1
    print("OK  postgres+pgvector, schema, ollama models all reachable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
