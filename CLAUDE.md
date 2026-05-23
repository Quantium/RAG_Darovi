# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This is the **orchestrator** for the RAG Darovi platform. It contains no application source code: every runtime lives in a git submodule. The orchestrator owns `docker-compose.yml`, the `.env` template, Makefile targets, scripts, and documentation that ties the multi-repo system together.

## Submodule map

| Path | Source repo | Responsibility |
|------|-------------|----------------|
| `services/ingest_raw` | `Quantium/rag-service-ingest-raw` | Ingestion from local folder or Google Drive → MinIO RAW |
| `services/extract_text` | `Quantium/rag-service-extract-text` | Text extraction RAW → MinIO TEXT; routes scanned pages to vision |
| `services/retrieval_admin` | `Quantium/rag-service-retrieval-admin` | Retrieval API: embed query → Milvus search → Redis cache |
| `services/chatbot_response` | `Quantium/rag-service-chatbot-response` | Chat REST + WebSocket; calls retrieval-admin; Ollama LLM |
| `dashboard/rag-dashboard-core` | `Quantium/rag-legacy-core` | FastAPI dashboard + Celery monolith (worker, beat, vision worker) |
| `schema/rag-schema` | `Quantium/rag-schema` | Shared Alembic migrations |
| `qa/rag-e2e-contracts` | `Quantium/rag-e2e-contracts` | Cross-service HTTP contracts + Playwright e2e |

The `dashboard/rag-dashboard-core` submodule builds four Compose services: `dashboard-api`, `dashboard-worker`, `dashboard-worker-vision`, and `dashboard-beat`.

## Common commands

```bash
# First-time setup
git submodule update --init --recursive
cp .env.example .env

# Update all submodules to their latest published commits
make submodules

# Stack lifecycle
make up            # docker compose up -d
make down          # docker compose down
make docker-build  # docker compose build
make clean         # docker compose down -v + rm __pycache__

# Verification
make qa-dashboard  # dashboard core unit suite
make qa-services   # all service submodule unit suites
make qa-cross      # cross-service contract tests (requires stack up)
make qa-all        # all three gates in order

# Smoke check after `make up`
docker compose ps
curl -fsS http://localhost:8000/status
curl -fsS http://localhost:8010/health
curl -fsS http://localhost:8020/health
./scripts/verify-multi-repo-local.sh

# TLS (optional local HTTPS)
make tls-certs
```

## Pipeline state machine (`file_records`)

The PostgreSQL `file_records` table drives the entire ingestion pipeline. Key status columns and their progression:

- `raw_status`: `pending` → `synced` (set by `ingest_raw` on successful MinIO upload, includes `raw_checksum` SHA-256)
- `text_status`: `pending` → `ready_for_embedding` (set by `extract_text` when text is in MinIO TEXT bucket)
- `status`: `downloaded` → `converted` → `embedded`

`extract_text` only picks rows where `raw_status='synced'` AND `raw_checksum IS NOT NULL`. The Celery worker only dispatches to Milvus when `text_status='ready_for_embedding'`. If files are stuck, see `scripts/README-backfill.md` for diagnostic SQL and remediation options.

## Container port map

| Port | Container |
|------|-----------|
| 8000 | `dashboard-api` (main UI + API) |
| 8010 | `retrieval-admin-service` |
| 8020 | `chatbot-response-service` |
| 5432 | PostgreSQL |
| 6379 | Redis |
| 9000/9001 | MinIO API / console |
| 19530 | Milvus |
| 11435 | Ollama (embed + chat; host port avoids conflict with local Ollama at 11434) |
| 11436 | Ollama Vision (llama3.2-vision:11b, isolated VRAM) |

Redis logical DBs: 0 = Celery broker, 1 = Celery results, 2 = retrieval cache + conversation history.

Two Ollama containers are intentional: `ollama-vision` is isolated so VLM calls cannot evict embedding/chat models from VRAM.

## Where to make a change

| Goal | Repo |
|------|------|
| Chat API behavior | `services/chatbot_response` |
| Retrieval logic | `services/retrieval_admin` |
| Text extraction | `services/extract_text` |
| Ingestion source | `services/ingest_raw` |
| Dashboard worker / vision pipeline | `dashboard/rag-dashboard-core` |
| DB schema / migrations | `schema/rag-schema` |
| Cross-service contracts or e2e specs | `qa/rag-e2e-contracts` |
| Compose, env vars, scripts | this repo |

When a change touches both a service and the orchestrator (e.g. a new env var), make the service change first, push it, then bump the submodule pointer here with `git add <submodule-path> && git commit`.

## Mandatory constraints

- **Schema safety**: never modify `file_records` or related tables without confirming migration impact with the requester. All schema changes go through `schema/rag-schema` (Alembic).
- **Submodule discipline**: application code changes must happen in the submodule's own repo, not by editing files in the mounted path directly (those edits are untracked by the orchestrator's git).
- **Documentation in English** across all repos.
- **Rollback baseline**: tag `v0.8.0` is the recovery anchor pre-split. See `docs/repo-split/VERIFICATION_GATES.md` for rollback procedure.
