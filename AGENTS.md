# AGENTS.md — AI Agent Context for RAG Darovi

**Canonical briefing for coding agents** (Claude Code, Cursor, GitHub Copilot, Codex, etc.) working in this repository. Read this file fully before taking any action. It encodes invariants that are not derivable from the code alone.

For Claude Code specifically, the authoritative behavioral contract is `CLAUDE.md`.

---

## Domain Context

**Darovi** is a Mexican distributor of medicines and health assets, supplying government dependencies (IMSS, ISSSTE, Secretaría de Salud) through CEDIS (Centros de Distribución). Contracts are large, multi-document bundles subject to strict health and procurement regulations. Documents are heterogeneous: scanned PDFs with stamps and signatures, package photos, Excel catalogs, Word specifications.

**This platform** solves: convert an unstructured document archive into a semantically-searchable, conversational knowledge base. Core pipeline: ingest binaries → extract text (digital layer or vision OCR) → embed chunks as high-dimensional vectors → store in a vector database → retrieve semantically at query time → generate LLM answers with source citations.

Architecture: **hybrid** — ingestion and dashboard run on-premises in Docker; the public-facing chatbot runs on AWS EC2. PostgreSQL is hosted on Neon.tech (serverless). Vectors are hosted on Zilliz Cloud (managed Milvus). Both environments share the same managed databases.

```
ON-PREMISES (local Docker)              AWS EC2 (public internet)
────────────────────────────            ──────────────────────────────
docker-compose.yml                      docker-compose.aws.yml
  Ingestion pipeline                      nginx (TLS, port 443)
  Dashboard API + Celery                  chatbot-response-service
  MinIO (object storage)                  retrieval-admin-service
  Redis (broker + cache)                  Redis (conversation cache)
                  │                               │
                  └──────────┬────────────────────┘
                             │
               SHARED MANAGED SERVICES
               Neon.tech (PostgreSQL)
               Zilliz Cloud (Milvus vectors)
```

---

## Repository Structure

**Monorepo** — submodules dissolved 2026-05. All service code is tracked as regular files.

```
services/
  ingest_raw/          FastAPI + APScheduler. Watches LOCAL_SOURCE_FOLDER; SHA-256 dedup;
                       uploads to MinIO raw-files; creates file_records rows.
  extract_text/        FastAPI + APScheduler. Downloads RAW from MinIO; runs pdfplumber /
                       python-docx / openpyxl; quality-checks text (alpha ratio, char count);
                       emits vision sentinels; writes markdown to MinIO converted-texts.
  retrieval_admin/     FastAPI. POST /retrieve: embed query via OpenAI → Milvus COSINE
                       search → Redis cache (TTL 5 min) → return chunks + source metadata.
  chatbot_response/    FastAPI + WebSocket. POST /chat and WS /ws/chat: load Redis history →
                       call retrieval-admin → call DeepSeek LLM → persist turn → return answer.

dashboard/
  rag-dashboard-core/  FastAPI API + Celery worker/beat/vision monolith.
    src/api/           FastAPI routes: /status /chat /ingest /dashboard/* /files/*
    src/worker/        Celery tasks: download_file, embed_file, vision_extract,
                       poll_text_ready_for_embedding, restart_vectorization.
    src/vectorizer/    OpenAI embedder + MilvusStore (ORM-style PyMilvus, due for migration
                       to MilvusClient in a future sprint).
    src/vision/        OpenAICompatVisionClient (httpx, async). CircuitBreaker (Redis-backed).
                       Tesseract fallback. Retry with image downscale on timeout.
    src/converter/     pdfplumber / docx / xlsx converters with per-page quality check.
    config/settings.py Pydantic-settings. Single source of truth for all env vars.

schema/
  rag-schema/          Alembic migrations against Neon.tech. Run locally and automatically
                       on every EC2 deploy (GitHub Actions). Schema changes MUST go through here.

qa/
  rag-e2e-contracts/   Cross-service HTTP contracts + Playwright browser tests.

scripts/
  backup.sh            Backup: pg_dump + Python minio streaming tar + Milvus parquet export.
  restore.sh           Restore: psql restore + minio put_object + Milvus drop/recreate/insert.

nginx/
  aws.conf             Nginx reverse proxy config (HTTP→HTTPS redirect, WebSocket upgrade).
  certs/               Self-signed TLS certs for EC2 (gitignored — generated on server).

docker-compose.yml     Full local stack (dashboard, ingestion, MinIO, Celery, Redis).
docker-compose.aws.yml Minimal AWS stack: nginx + chatbot-response + retrieval-admin + redis.

.github/workflows/
  deploy-aws.yml       GitHub Actions: SSH into EC2 → git pull → alembic upgrade → docker compose up.
                       Secrets: EC2_IP, EC2_SSH_KEY. Triggered on push to main.
```

### Service deployment matrix

| Service | Local | AWS EC2 |
|---------|-------|---------|
| `dashboard-api` | ✅ :8000 (HTTPS) | ❌ |
| `dashboard-worker` | ✅ | ❌ |
| `dashboard-worker-vision` | ✅ | ❌ |
| `dashboard-beat` | ✅ | ❌ |
| `ingest-raw-service` | ✅ :8030 | ❌ |
| `extract-text-service` | ✅ :8031 | ❌ |
| `retrieval-admin-service` | ✅ :8010 | ✅ (internal, not exposed) |
| `chatbot-response-service` | ✅ :8020 | ✅ (via nginx :443) |
| `nginx` | ❌ | ✅ :80/:443 |
| `redis` | ✅ container | ✅ container (separate volume) |
| `minio` | ✅ :9000/:9001 | ❌ |
| `postgres` | ❌ → Neon.tech | ❌ → Neon.tech |
| `milvus` | ❌ → Zilliz Cloud | ❌ → Zilliz Cloud |

---

## Inference Stack

No local inference containers exist. All AI runs via external APIs:

| Capability | Provider | Model | SDK call |
|-----------|----------|-------|----------|
| Text embeddings | OpenAI | `text-embedding-3-large` (3072 dims) | `client.embeddings.create()` |
| Vision OCR | OpenAI | `gpt-4o` | `client.chat.completions.create()` with `image_url` content |
| Chat completion | DeepSeek | `deepseek-chat` | `openai.AsyncOpenAI(base_url=deepseek_url)` |

OpenAI and DeepSeek both use the OpenAI Python SDK. DeepSeek is OpenAI-API-compatible at `https://api.deepseek.com/v1/`.

---

## Data Flow Invariants

### Ingestion pipeline (critical state machine)

```
file_records.raw_status:   pending → synced          (ingest_raw writes raw_checksum SHA-256)
file_records.text_status:
  pending → ready_for_embedding                       (extract_text: text OK)
  pending → vision_pending                            (extract_text: low-quality text detected)
  vision_pending → vision_processing → ready_for_embedding  (Celery vision_extract task)
  ready_for_embedding → embedding_queued → embedded   (Celery embed_file task)
file_records.status: downloaded → converted → embedded
```

**Guard conditions** (encoded in service logic, do not break):
- `extract_text` only reads rows where `raw_status='synced' AND raw_checksum IS NOT NULL`
- `embed_file` only processes rows where `text_status='ready_for_embedding'`
- `poll_text_ready_for_embedding` is the only entry point to `embedding_queued` — do not set this status directly
- `chunk_count` on `file_records` reflects actual Milvus entity count for that file, kept in sync by `embed_file`

### Milvus collection schema (must not drift)

Collection: `rag_documents` · Index: HNSW COSINE · M=16 efConstruction=256 · dim=3072  
Partitions: `doc`, `sheet`, `pdf` (determined by `document_type` field on each chunk)  
Primary key: `id` VARCHAR — format: `{source_file_id}_{chunk_index}`  
Fields: `id`, `source_file_id`, `source_name`, `document_type`, `section_title`, `chunk_index` (INT64), `text` (VARCHAR 65535), `embedding` (FLOAT_VECTOR 3072)

**Invariant**: `EMBED_DIM` env var and Milvus collection `dim` must always agree. Changing either requires `drop_collection_if_exists()` + `ensure_milvus_collection()` + full re-embedding.

### MinIO bucket layout

| Bucket | Key format | Contents |
|--------|-----------|---------|
| `raw-files` | `{drive_file_id}` | Original binary (PDF, DOCX, XLSX, image) |
| `converted-texts` | `{drive_file_id}.md` | Extracted markdown text |
| `a-bucket` | Milvus internal paths | Milvus vector segment files (do not modify) |

---

## Code Patterns and Style

**Language**: Python 3.11+. Type hints everywhere. `from __future__ import annotations` on all modules.

**Settings**: `pydantic-settings` `BaseSettings`. All config comes from env vars. Field `embed_api_key: SecretStr` maps to env var `EMBED_API_KEY` (case-insensitive). Never hardcode secrets.

**Async**: FastAPI routes are async. Celery tasks are sync (they use `create_engine` + `Session`, not `AsyncSession`). The `database_url_sync` setting exists specifically for Celery workers.

**Logging**: `structlog` with `logger.bind(key=value)` pattern. Event names are `module.action` (e.g., `milvus.upserted`, `task.completed`). Do not use `print()` for observability.

**Error handling**: Tasks use `@app.task(bind=True, max_retries=N)` with `self.retry(exc=e, countdown=N)`. Retry counts and backoffs are per-task (not global). Vision tasks downscale images before retry.

**Imports**: Absolute imports using `src.` prefix in dashboard (e.g., `from src.vision.client import OpenAICompatVisionClient`). Service imports use `app.` prefix.

**Tests**: `pytest` with `pytest-asyncio`. Tests live in `tests/` within each service/dashboard. Use `make install && make test` inside each directory.

---

## Known Architectural Debt

- `MilvusStore` in `src/vectorizer/milvus_store.py` uses deprecated ORM-style PyMilvus API (`connections.connect`, `Collection`, `utility.*`). PyMilvus recommends `MilvusClient` (from pymilvus 2.4+). Functional but will break in pymilvus 3.1.
- `dashboard-api` runs HTTPS (TLS via Uvicorn). Internal health checks and curl commands require `-k` (skip cert verification) for self-signed certs.
- The `retrieval-admin-service` has a legacy `/answer` endpoint that calls a small LLM. This is not used by `chatbot_response` in production (which calls its own LLM chain). It exists for direct API consumers.

---

## Critical Constraints for Agents

1. **Schema changes**: Never modify `file_records`, `sync_state`, `drive_connection`, or `extracted_documents` table definitions without explicitly alerting the requester and confirming migration impact. Schema changes require a new Alembic migration in `schema/rag-schema/`.

2. **Volume safety**: `docker compose down -v` deletes all named volumes including Milvus vectors and MinIO files. Always run `./scripts/backup.sh` before any operation involving volumes.

3. **Env var coupling**: Adding a new env var requires changes in: (a) the service's `settings.py`, (b) `docker-compose.yml` environment block, and (c) `.env.example`. All three must be updated atomically.

4. **English-only documentation**: All comments, docstrings, commit messages, PR descriptions, and documentation files must be in English. The user communicates in Spanish; output code and docs in English.

5. **No direct Milvus data modification**: Only `embed_file` and `restart_vectorization` tasks should write to Milvus. Never insert/delete vectors directly from ad-hoc scripts unless explicitly requested by the requester.

6. **Celery task idempotency**: The `embed_file` task calls `store.delete_by_source(drive_file_id)` before inserting — it is idempotent by design. Do not add guards that skip re-insertion.

---

## Build and Test Commands

```bash
# Full stack
docker compose up -d --build          # build + start all services
docker compose up -d --build --no-deps <svc>  # rebuild single service

# Service tests (each has its own venv via make install)
cd services/ingest_raw    && make install && make test
cd services/extract_text  && make install && make test
cd services/retrieval_admin && make install && make test
cd services/chatbot_response && make install && make test
cd dashboard/rag-dashboard-core && make install && make test

# Cross-service (requires stack running)
cd qa/rag-e2e-contracts && make install && make test

# Backup (always before destructive ops)
./scripts/backup.sh
./scripts/restore.sh backups/YYYYMMDD_HHMMSS
```

---

## Port Map

```
8000 → dashboard-api    (HTTPS; main UI + REST + /dashboard/*)
8010 → retrieval-admin  (HTTP; POST /retrieve, POST /answer, GET /status)
8020 → chatbot-response (HTTP + WebSocket; POST /chat, WS /ws/chat)
5432 → PostgreSQL 16
6379 → Redis 7          (DB0: Celery broker, DB1: results, DB2: cache+history)
9000 → MinIO API        (S3-compatible)
9001 → MinIO console    (browser UI)
19530→ Milvus gRPC
```
