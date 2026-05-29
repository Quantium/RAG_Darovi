# CLAUDE.md — Project Memory for Claude Code

This file is loaded automatically at every Claude Code session. It is a **behavioral contract**, not documentation. Every line consumes context — keep it specific and verifiable.

---

## Repository Identity

**Monorepo** — all service code lives directly in this repository. Submodules were dissolved in May 2026; all paths below are regular tracked files.

```
services/ingest_raw/         ← RAW ingestion: LABORATORIOS/ → MinIO raw-files
services/extract_text/       ← Text extraction: MinIO RAW → MinIO converted-texts
services/retrieval_admin/    ← Retrieval API: OpenAI embed → Milvus search → Redis cache
services/chatbot_response/   ← Chat API: retrieval-admin + DeepSeek LLM + Redis history
dashboard/rag-dashboard-core/← FastAPI + Celery monolith (worker, beat, vision worker)
schema/rag-schema/           ← Alembic migrations (schema source of truth)
qa/rag-e2e-contracts/        ← Cross-service HTTP contracts + Playwright e2e
docker-compose.yml           ← Orchestration entrypoint
.env / .env.example          ← Runtime configuration (gitignored)
scripts/backup.sh            ← Point-in-time backup: PG + MinIO texts + Milvus parquet
scripts/restore.sh           ← Restore from backup directory
```

---

## Inference Providers (current state)

| Function | Provider | Model | Env var |
|----------|----------|-------|---------|
| Embeddings | OpenAI | `text-embedding-3-large` (dim=3072) | `EMBED_API_KEY` |
| Vision OCR | OpenAI | `gpt-4o` | `VISION_EXTERNAL_API_KEY` |
| Chat LLM | DeepSeek | `deepseek-chat` | `DEEPSEEK_API_KEY` |

Ollama is **not** used. Google Drive is **not** used.

---

## Common Commands

```bash
# Stack
make up            # docker compose up -d
make down          # docker compose down  (volumes preserved)
make clean         # docker compose down -v  ← DELETES ALL VOLUMES
make docker-build  # docker compose build

# Rebuild one service after code change
docker compose up -d --build --no-deps <service-name>

# Smoke check
docker compose ps
curl -k https://localhost:8000/status
curl http://localhost:8010/health
curl http://localhost:8020/health

# Test suites (each bootstraps its own venv)
make qa-dashboard  # dashboard/rag-dashboard-core pytest
make qa-services   # all four services
make qa-cross      # qa/rag-e2e-contracts (requires stack up)
make qa-all        # all three gates

# Backup / restore
./scripts/backup.sh                    # PG + MinIO texts + Milvus parquet
./scripts/backup.sh --include-raw      # also raw-files (~4 GB extra)
./scripts/restore.sh backups/YYYYMMDD_HHMMSS
```

---

## Python Tooling — always use `uv`

All Python commands must go through `uv`. Never call `pip`, `python`, or `python -m venv` directly.

### Running scripts and modules

```bash
# Instead of: python script.py
uv run script.py

# Instead of: python -m pytest
uv run pytest

# Instead of: python -m alembic upgrade head
uv run alembic upgrade head

# Pass extra args normally
uv run script.py --arg value
```

### Installing dependencies

```bash
# Instead of: pip install -r requirements.txt
uv pip install -r requirements.txt

# Exact sync — also removes packages not in the file
uv pip sync requirements.txt

# Install a single package
uv pip install httpx

# Install with extras
uv pip install "fastapi[standard]"
```

### Locking / compiling requirements

```bash
# Pin all transitive deps from requirements.in → requirements.txt
uv pip compile requirements.in -o requirements.txt

# Upgrade a specific package while keeping the rest pinned
uv pip compile requirements.in -o requirements.txt --upgrade-package httpx
```

### Virtual environments

```bash
# Instead of: python -m venv .venv
uv venv

# With a specific Python version
uv venv --python 3.12
```

### Project mode (pyproject.toml)

```bash
uv add requests          # add dependency + update lockfile
uv remove requests       # remove dependency
uv sync                  # install all deps from lockfile into .venv
uv sync --no-dev         # skip dev dependencies
uv lock --upgrade-package requests   # bump one package in the lockfile
```

---

## Pipeline State Machine (`file_records`)

Every file progresses through PostgreSQL `file_records` columns. Never modify these states manually without understanding the full chain.

```
raw_status:   pending → synced            (ingest_raw: MinIO upload + SHA-256 checksum)
text_status:  pending → ready_for_embedding    (extract_text: text written to MinIO)
              pending → vision_pending          (extract_text: scanned page detected)
              vision_pending → vision_processing → ready_for_embedding  (GPT-4o OCR)
              ready_for_embedding → embedding_queued → embedded  (Celery embed_file task)
status:       downloaded → converted → embedded
```

`extract_text` only processes rows where `raw_status='synced' AND raw_checksum IS NOT NULL`.
Celery beat fires `poll_text_ready_for_embedding` every `EMBEDDING_POLL_INTERVAL_SECONDS` (default 300s).
Files stuck in `embedding_queued` = OpenAI 429 rate limit; they retry automatically.

---

## Where to Make Changes

| Goal | Edit path |
|------|-----------|
| Chat API behavior | `services/chatbot_response/app/` |
| Retrieval / embedding logic | `services/retrieval_admin/app/` |
| Text extraction / OCR routing | `services/extract_text/app/` |
| File ingestion source | `services/ingest_raw/app/` |
| Dashboard API routes | `dashboard/rag-dashboard-core/src/api/` |
| Celery tasks / embedding pipeline | `dashboard/rag-dashboard-core/src/worker/tasks.py` |
| Vision OCR client | `dashboard/rag-dashboard-core/src/vision/client.py` |
| Milvus schema / index | `dashboard/rag-dashboard-core/src/vectorizer/milvus_store.py` |
| DB schema / migrations | `schema/rag-schema/` (Alembic) |
| Docker Compose / env vars | `docker-compose.yml`, `.env.example` |
| Backup / restore scripts | `scripts/backup.sh`, `scripts/restore.sh` |

---

## Mandatory Constraints

**Schema safety**: Never modify `file_records` or related tables without confirming migration impact. All schema changes go through `schema/rag-schema` using Alembic. Alert the requester before touching schema.

**Env var naming**: Settings use `pydantic-settings` which maps `SNAKE_CASE` env vars to lowercase field names. The dashboard settings file is `dashboard/rag-dashboard-core/config/settings.py`; each service has `app/settings.py`. Always verify both sides when adding a new env var.

**Milvus + embeddings coupling**: `EMBED_DIM` and `EMBED_MODEL` must match the stored collection schema. Changing either requires dropping and recreating the Milvus collection (`store.drop_collection_if_exists()`) and re-running the full embedding pipeline.

**Volume safety**: `make clean` runs `docker compose down -v` which deletes `pgdata`, `miniodata`, `milvusdata`, `redisdata`. Run `./scripts/backup.sh` before any destructive operation.

**English documentation**: All code comments, docstrings, commit messages, and documentation files must be in English.

---

## Port Map

| Port | Service |
|------|---------|
| 8000 | `dashboard-api` (HTTPS, main UI) |
| 8010 | `retrieval-admin-service` (HTTP, REST only, no UI) |
| 8020 | `chatbot-response-service` (HTTP + WebSocket) |
| 5432 | PostgreSQL |
| 6379 | Redis |
| 9000 / 9001 | MinIO API / console |
| 19530 | Milvus gRPC |

Redis DBs: 0 = Celery broker (AOF persistent), 1 = Celery results, 2 = retrieval cache + conversation history.
