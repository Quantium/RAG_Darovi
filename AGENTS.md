# AGENTS.md — AI Agent Build Guide

## Project Overview

RAG pipeline application: terabyte-scale document ingestion from Google Drive, vectorization via Ollama, and LLM-powered Q&A with source citations and multi-turn conversation memory. Built with Python 3.11, FastAPI, Celery, Milvus, PostgreSQL, MinIO, and Redis (isolated DBs).

## Mandatory Principles

### TDD (Red-Green-Refactor)

1. **RED** — Write failing tests first (Phase 2 defines all test stubs).
2. **GREEN** — Implement minimum code to pass tests.
3. **REFACTOR** — Clean up while keeping tests green.

Never skip a failing test to start the next step. Run `pytest` after every implementation change.

### SOLID

- **Single Responsibility**: One concern per module.
- **Open/Closed**: `FileConverter` protocol — add converters without modifying existing ones.
- **Liskov Substitution**: All converters interchangeable behind the protocol.
- **Interface Segregation**: Minimal surfaces for Storage, LLM, and DB interfaces.
- **Dependency Inversion**: Depend on abstractions (Protocols), not concrete implementations. All services accept injected dependencies for testability.

### Code Quality

- Python 3.11+ type hints on all public functions.
- Pydantic validation for all config and API schemas.
- `ruff check` + `ruff format` + `mypy --strict` must pass.
- `async/await` for all I/O-bound operations.
- `structlog` with `request_id`, `file_id`, `task_name` for structured logging.
- Exponential backoff retries (max 5), circuit breakers for external APIs.
- All documentation and test names in English.

## Configuration Strategy

All modules read from a single `Settings` instance (`config/settings.py`) via Pydantic Settings. Override chain: **env vars > `.env` file > code defaults**. No module reads `os.environ` directly — always inject `Settings`. Sensitive fields use `SecretStr`.

Key settings additions:
- `database_url_sync` — sync `psycopg2` URL for Celery tasks (avoids async event loop issues).
- `redis_broker_url` / `redis_result_url` / `redis_cache_url` — isolated Redis DBs (0/1/2).
- `api_key` — optional API key for endpoint auth (empty = disabled).
- `google_sheets_credentials` — separate credentials path for Sheets write scope.

## Project Structure

```
RAG_Darovi_test/
├── config/settings.py          # Pydantic Settings (single source of truth)
├── src/
│   ├── main.py                 # CLI: serve | worker | beat | ingest | query
│   ├── logging.py              # structlog configuration
│   ├── drive/                  # Google Drive auth (readonly) + full_sync + incremental_sync (with deletion detection)
│   ├── storage/                # MinIO + local fallback (StorageBackend protocol)
│   ├── converter/              # FileConverter protocol + PDF/Docs/Sheets/Docx/Xlsx/Text impls + factory
│   ├── vectorizer/             # Chunker (tiktoken), BatchEmbedder, MilvusStore
│   ├── metadata/               # PostgreSQL repository — both async (AsyncSession) and sync (Session) variants
│   ├── worker/                 # Celery app, RetryableTask, tasks (incl. delete_file_vectors), sync helpers
│   ├── scheduler/              # Celery Beat pipeline (with distributed lock)
│   ├── rag/                    # Retriever, LLMClient, ConversationStore, RAG chain
│   ├── generator/              # SQLGenerator (with SQL safety validation), DBWriter (restricted schema), SheetsWriter
│   ├── automation/             # Engine + YAML templates
│   └── api/                    # FastAPI app factory (with API key auth), routes, schemas
├── static/                     # Chatbot SPA (index.html, styles.css, app.js)
├── tests/                      # Mirrors src/ structure with test_ prefix
├── docker-compose.yml          # Redis, PostgreSQL, Milvus, MinIO, Ollama, app services
├── Dockerfile                  # Multi-stage build (prod deps only)
├── requirements.txt            # Production deps
├── requirements-dev.txt        # Dev/test deps (extends production)
└── plans/                      # Detailed phase plans (read-only reference)
```

## Build Phases (Execute in Order)

Each phase depends on the previous. Detailed plans live in `plans/PLAN_0N_*.md`. Always read the relevant plan file before starting a phase.

### Phase 1 — Setup & Infrastructure
**Plan**: `plans/PLAN_01_SETUP.md`
**Builds**: venv, deps (incl. `python-docx`, `openpyxl`, `beautifulsoup4`, `tiktoken`), `config/settings.py` (with `database_url_sync`, isolated Redis URLs, `api_key`), directory scaffold, `.env.example`, `.gitignore`, `.dockerignore`, `Dockerfile`, `docker-compose.yml`, `Makefile`
**Success**: `docker compose up -d` healthy; `from config.settings import Settings` works; `import src` works.

### Phase 2 — TDD Test Stubs (RED)
**Plan**: `plans/PLAN_02_TDD_TESTS.md`
**Builds**: `pyproject.toml`, `tests/conftest.py` (fixtures with isolated Redis DBs, mocks), all test files across every module. Includes tests for: full_sync, deletion detection, new converters, conversation memory, SQL safety, API key auth. `test_embed_task_calls_embedder` marked `xfail` until Phase 5.
**Success**: `pytest --collect-only` finds all tests; `pytest` runs and all fail with `ImportError` or `NotImplementedError` (xfail tests expected to fail).

### Phase 3 — Download & Conversion
**Plan**: `plans/PLAN_03_DOWNLOAD_CONVERT.md`
**Builds**: `StorageBackend` protocol + `MinIOStorage` + `LocalStorage`, `MetadataRepository` (async) + `SyncMetadataRepository` (sync for Celery), `DriveAuth` (readonly scope), `DriveDownloader` (`full_sync` + `incremental_sync` with deletion detection), `FileConverter` protocol + PDF/Docs/Sheets/Docx/Xlsx/Text converters + factory, `DocumentChunker` (with `tiktoken`), `structlog` setup.
**Parallelizable**: Storage and Metadata are independent. Converters are independent of Drive modules. Chunker is independent.
**Success**: `pytest tests/test_storage/ tests/test_metadata/ tests/test_drive/ tests/test_converter/ tests/test_vectorizer/test_chunker.py -v` all GREEN.

### Phase 4 — Celery Workers & Scheduler
**Plan**: `plans/PLAN_04_CRON_SYNC.md`
**Builds**: `celery_app.py` (config with isolated Redis DBs, `RetryableTask` with sync `on_failure`, beat schedule), `task_helpers.py` (using sync `psycopg2` sessions), `tasks.py` (download, convert with unsupported MIME handling, embed placeholder, `delete_file_vectors`, chain dispatch), `scheduler/pipeline.py` with distributed Redis lock.
**Key**: Three queues (`download`, `convert`, `embed`). `embed_file` stays as `NotImplementedError` placeholder. Distributed lock prevents concurrent syncs. Deletion tasks clean up Milvus + MinIO + PG.
**Success**: `pytest tests/test_worker/ tests/test_scheduler/ -v` GREEN (embed test `xfail`).

### Phase 5 — Embedding & Vector Storage
**Plan**: `plans/PLAN_05_EMBEDDING.md`
**Builds**: `BatchEmbedder` (httpx + Ollama `/api/embed`), `MilvusStore` (HNSW index, COSINE metric, partitions), completes `embed_file` task.
**Key**: Batch embed (64 texts), batch Milvus insert (1000 vectors). `delete_by_source` before re-upsert for modified files.
**Success**: `pytest tests/test_vectorizer/ tests/test_worker/ -v` all GREEN.

### Phase 6 — LLM, RAG, Generators, Automations
**Plan**: `plans/PLAN_06_LLM.md`
**Builds**: `Retriever` (semantic search + Redis cache on DB 2), `OpenAICompatibleLLMClient` (Ollama/Gemini/DeepSeek via factory + circuit breaker), `ConversationStore` (Redis-backed multi-turn memory), `rag_answer()` + `rag_answer_stream()` (with conversation history), `SQLGenerator` (with SQL safety whitelist/validation), `DBWriter` (restricted `rag_generator` user on `generated` schema), `SheetsWriter` (with `spreadsheets` scope), `AutomationConfig` templates + `AutomationEngine`.
**Parallelizable**: Retriever, LLM Client, and Conversation Store are independent. Generators depend on Retriever + LLM. Automation depends on generators.
**Success**: `pytest tests/test_rag/ tests/test_generator/ tests/test_automation/ -v` all GREEN.

### Phase 7 — FastAPI + Chatbot UI
**Plan**: `plans/PLAN_07_UI_CHATBOT.md`
**Builds**: API schemas, FastAPI app factory (lifespan wires all services + `ConversationStore` + API key auth middleware), REST + WebSocket routes (with conversation memory), CLI entry point (`argparse`), chatbot SPA (vanilla JS, WebSocket streaming with `conversation_id`, dark/light theme, source reference cards, API key support).
**Key**: Routes use `rag_answer`/`rag_answer_stream` from Phase 6 — no logic duplication. API key auth optional (disabled when `API_KEY` is empty). Static files mounted after router.
**Success**: `pytest -v` → 100% pass. UI at `http://localhost:8000` streams answers with sources and maintains conversation context.

## Infrastructure Services (Docker Compose)

| Service | Image | Port | Purpose |
|---|---|---|---|
| Redis | `redis:7-alpine` | 6379 | DB 0: Celery broker, DB 1: result backend, DB 2: cache + conversation memory |
| PostgreSQL | `postgres:16-alpine` | 5432 | Metadata DB (`public` schema) + generated SQL output (`generated` schema with restricted user) |
| Milvus | `milvusdb/milvus:v2.4-latest` | 19530 | Vector DB with HNSW index |
| MinIO | `minio/minio` | 9000/9001 | Object storage (raw files + converted text) |
| Ollama | `ollama/ollama` | 11434 | Embeddings (`nomic-embed-text`) + local LLM (`llama3`) |

## Data Flow

```
Google Drive → Celery Beat (distributed lock) → full_sync / incremental_sync
    Changed files → download_file → MinIO (raw) → convert_file → MinIO (text)
        → embed_file → Ollama (768-dim vectors) → Milvus (HNSW)
    Deleted files → delete_file_vectors → Milvus + MinIO + PostgreSQL cleanup
    → User Query → Retriever → LLM (with conversation memory) → Answer + Source Citations
```

## Key Architectural Patterns

| Pattern | Where | Why |
|---|---|---|
| Protocol (structural typing) | `StorageBackend`, `FileConverter`, `LLMClient`, `VectorStore` | DI + testability without ABC overhead |
| Factory | `get_converter(mime_type)`, `create_llm_client(settings)` | Open/Closed — add types without modifying callers |
| Strategy | LLM providers via `OpenAICompatibleLLMClient` | Single impl, config-driven provider swap |
| Chain of Responsibility | Celery `download → convert → embed` | Decoupled pipeline stages, independent scaling |
| Circuit Breaker | `LLMClient._check_circuit()` | Prevent cascading failures on external APIs |
| Repository | `MetadataRepository` (async) + `SyncMetadataRepository` (sync) | Isolate DB access; sync variant for Celery, async for FastAPI |
| Distributed Lock | Redis `SET NX` in `run_incremental_sync` | Prevent concurrent syncs from overlapping |
| Defense in Depth | SQL whitelist + restricted DB user + isolated schema | LLM-generated SQL cannot damage pipeline data |

## Testing Conventions

- **Unit tests**: Mock external deps (MinIO, Drive, Ollama, Milvus, Redis). Use DI constructor params.
- **Integration tests**: Mark with `@pytest.mark.integration`. Require Docker services.
- **Async tests**: `asyncio_mode = "auto"` in pyproject.toml. Use `async def test_*`.
- **Fixtures**: Shared in `tests/conftest.py` — `settings`, `db_session`, `mock_minio_client`, `mock_drive_service`, `mock_ollama_client`, `mock_httpx_client`, `mock_milvus_client`, `mock_redis_client`, `sample_pdf_bytes`, `sample_text`.

## Common Commands

```bash
make install     # pip install -r requirements-dev.txt
make up          # docker compose up -d
make down        # docker compose down
make test        # pytest -v --tb=short
make lint        # ruff check src/ tests/
make format      # ruff format src/ tests/
make typecheck   # mypy --strict src/
make clean       # docker compose down -v + remove __pycache__
```

## Definition of Done

- `pytest -v` passes 100% (no skipped, no xfail).
- `mypy --strict src/` reports zero errors.
- `ruff check src/ tests/` and `ruff format --check src/ tests/` report zero issues.
- `docker compose up -d` starts all services healthy.
- First run performs full Drive scan; subsequent runs use incremental sync with distributed lock.
- Deleted Drive files trigger automatic cleanup of vectors, objects, and metadata.
- Celery Beat triggers automatic incremental sync on schedule.
- Chatbot UI at `http://localhost:8000` streams answers via WebSocket with source references and multi-turn conversation context.
- API endpoints protected by `X-API-Key` when configured.
- LLM-generated SQL validated via whitelist and executed under restricted DB user on isolated schema.
- `GET /status` returns accurate pipeline progress.
- Modified Drive files are automatically re-downloaded, re-converted, and re-indexed without stale vectors.
