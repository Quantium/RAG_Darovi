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
docker-compose.yml           ← Local-only orchestration (full stack)
docker-compose.aws.yml       ← AWS-only orchestration (chatbot services only)
nginx/aws.conf               ← Nginx TLS reverse proxy config for AWS
.env / .env.example          ← Runtime configuration (gitignored)
.env.aws                     ← AWS env vars — lives at ~/RAG_Darovi/.env.aws on EC2, never committed
scripts/backup.sh            ← Point-in-time backup: PG + MinIO texts + Milvus parquet
scripts/restore.sh           ← Restore from backup directory
```

---

## Deployment Architecture (Hybrid)

Two independent environments share the same managed cloud services (Neon + Zilliz).

```
LOCAL (on-premises)                          AWS EC2 (public internet)
─────────────────────────────────────        ─────────────────────────────────────
docker-compose.yml                           docker-compose.aws.yml
  dashboard-api         :8000 (HTTPS)          nginx                :443/:80
  dashboard-worker                             chatbot-response-service :8020
  dashboard-worker-vision                      retrieval-admin-service  :8010 (internal)
  dashboard-beat                               redis (container)
  ingest-raw-service    :8030
  extract-text-service  :8031
  retrieval-admin-service :8010               ↑ Port 8010 NOT exposed to internet
  chatbot-response-service :8020
  redis (container)
  minio                 :9000/:9001
  ─────────────────────────────────          ─────────────────────────────────────
         │                                            │
         └──────────────────┬─────────────────────────┘
                            │
              SHARED MANAGED SERVICES
              Neon.tech PostgreSQL     (DATABASE_URL / DATABASE_URL_SYNC)
              Zilliz Cloud (Milvus)    (MILVUS_URI / MILVUS_TOKEN)
```

**Rules:**
- `docker-compose.yml` — for local development and ingestion pipeline only. Never run on EC2.
- `docker-compose.aws.yml` — for EC2 only. No MinIO, no dashboard, no Celery.
- Both stacks read from the same Neon DB and Zilliz collection.
- `.env.aws` is created on EC2 via `scp` from local `.env`; only the two DATABASE_URL lines differ.

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
# Local stack
make up            # docker compose up -d
make down          # docker compose down  (volumes preserved)
make clean         # docker compose down -v  ← DELETES ALL VOLUMES
make docker-build  # docker compose build

# Rebuild one service after code change (local)
docker compose up -d --build --no-deps <service-name>

# Smoke check (local)
docker compose ps
curl -k https://localhost:8000/status
curl http://localhost:8010/health
curl http://localhost:8020/health

# AWS stack (run on EC2 or via deploy-aws.yml CI)
docker compose -f docker-compose.aws.yml --env-file ~/RAG_Darovi/.env.aws up -d --build
docker compose -f docker-compose.aws.yml ps
curl -k https://100.27.53.58/health     # public endpoint (ignore self-signed cert warning)
curl http://localhost:8010/health       # internal only — run from inside EC2

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

**Schema safety**: Never modify `file_records` or related tables without confirming migration impact. All schema changes go through `schema/rag-schema` using Alembic. Alert the requester before touching schema. Migrations are run automatically on every EC2 deploy by the GitHub Actions workflow.

**Env var naming**: Settings use `pydantic-settings` which maps `SNAKE_CASE` env vars to lowercase field names. The dashboard settings file is `dashboard/rag-dashboard-core/config/settings.py`; each service has `app/settings.py`. Always verify both sides when adding a new env var. When a variable is needed on AWS but not local (or vice versa), update `.env.example` and document the difference.

**Vector database**: The `rag_documents` collection is hosted on **Zilliz Cloud** (set via `MILVUS_URI` + `MILVUS_TOKEN` in `.env`). Local `milvus`/`milvus-etcd` containers exist in docker-compose but are stopped and not used. To restore local Milvus for dev, start them manually: `docker compose up -d milvus milvus-etcd` and unset `MILVUS_URI`.

**Milvus + embeddings coupling**: `EMBED_DIM` and `EMBED_MODEL` must match the stored collection schema. Changing either requires dropping and recreating the Zilliz collection (`store.drop_collection_if_exists()`) and re-running the full embedding pipeline.

**PostgreSQL**: Hosted on **Neon.tech** (serverless, free tier). Both local and AWS stacks point to the same Neon instance. Local `.env` uses `DATABASE_URL`/`DATABASE_URL_SYNC` pointing to Neon. EC2 `.env.aws` uses the same values. There is no local PostgreSQL container.

**Volume safety**: `make clean` runs `docker compose down -v` which deletes `miniodata`, `milvusdata`, `redisdata`. Run `./scripts/backup.sh` before any destructive operation. On EC2, `redisdata-aws` is the only persistent volume.

**`.env.aws` on EC2**: Lives at `~/RAG_Darovi/.env.aws` (relative to home dir, inside the cloned repo). Never committed to git. Created by `scp`-ing local `.env` then editing the database URLs. The compose file references it via `env_file: .env.aws` (relative path resolved from project root).

**English documentation**: All code comments, docstrings, commit messages, and documentation files must be in English.

---

## Port Map

### Local (docker-compose.yml)

| Port | Service |
|------|---------|
| 3000 | `gestor-licitaciones` (React/Vite SPA — standalone, not yet wired to backend) |
| 8000 | `dashboard-api` (HTTPS, main UI) |
| 8010 | `retrieval-admin-service` (HTTP, REST only, no UI) |
| 8020 | `chatbot-response-service` (HTTP + WebSocket) |
| 6379 | Redis |
| 9000 / 9001 | MinIO API / console |
| 19530 | Milvus gRPC — **local dev only**; production uses Zilliz Cloud via `MILVUS_URI` |

### AWS EC2 (docker-compose.aws.yml)

| Port | Service | Internet-facing? |
|------|---------|-----------------|
| 443 | `nginx` → `chatbot-response-service:8020` | Yes (HTTPS + WSS) |
| 80 | `nginx` (redirects to 443) | Yes |
| 8010 | `retrieval-admin-service` | **No — internal only** |
| 6379 | `redis` | No — internal only |

Redis DBs (both envs): 0 = Celery broker (AOF persistent, local only), 1 = Celery results (local only), 2 = retrieval cache + conversation history (used on AWS too).
