# AGENTS.md — AI Agent Guide

This file is the **canonical project briefing** for coding agents and LLMs. Read it before changing behavior, adding features, or debugging.

---

## What This Project Is

**RAG_Darovi** is a **retrieval-augmented generation (RAG) platform** that:

1. **Ingests documents** from **Google Drive** (full and incremental sync), stores raw and converted text in **object storage**, and tracks file metadata in **PostgreSQL**.
2. **Chunks** text, **embeds** chunks with **Ollama**, and **indexes** vectors in **Milvus** for semantic search.
3. **Answers user questions** via a **FastAPI** backend and **chat UI**: retrieves relevant chunks, calls an **OpenAI-compatible LLM** (Ollama, Gemini, DeepSeek, etc.), returns **answers with source citations**, and keeps **multi-turn conversation memory** in **Redis**.
4. **Runs the pipeline asynchronously** with **Celery** (download → convert → embed queues), **Celery Beat** for scheduled syncs, and a **distributed Redis lock** so only one incremental sync runs at a time.
5. **Optional generators**: LLM-assisted **SQL** (validated, executed on a restricted DB user / `generated` schema), **Google Sheets** writes, and **YAML-driven automations**.

**Scale intent:** designed for large corpora (many files); batching is used for embeddings and vector inserts.

**Stack:** Python 3.11+, FastAPI, Celery, Milvus, PostgreSQL, MinIO, Redis (isolated logical DBs), Ollama for embeddings and optional local LLM.

---

## End-to-End Behavior (Mental Model)

| Stage | Responsibility |
|--------|----------------|
| **Sync** | List changes on Drive; detect new/changed/deleted files; update metadata rows. |
| **Download** | Fetch file bytes; store in MinIO (raw). |
| **Convert** | MIME-based converters (PDF, Docs, Sheets, Docx, Xlsx, text, …) → normalized text in MinIO. |
| **Chunk + embed** | Token-aware chunking (`tiktoken`); `BatchEmbedder` calls Ollama (`/api/embed`, with fallback to legacy `/api/embeddings` on 404); vectors stored in Milvus keyed by source/chunk. |
| **Delete path** | If a Drive file disappears, **delete_file_vectors** removes Milvus rows, MinIO objects, and related PostgreSQL metadata so nothing stays stale. |
| **Query** | User message → embed query (or retriever path) → Milvus similarity search → optional Redis cache → assemble context → LLM → stream or JSON response with **sources** (file/chunk references). |
| **Memory** | `conversation_id` ties turns; history lives in Redis (cache DB), not only in the browser. |

---

## Data Flow (Compressed)

```
Google Drive
    → Celery Beat (+ distributed lock) → full_sync / incremental_sync
        → download_file → MinIO (raw)
        → convert_file → MinIO (text)
        → embed_file → Ollama embeddings → Milvus (HNSW, cosine)
    Deleted on Drive → delete_file_vectors → Milvus + MinIO + PostgreSQL

User (HTTP/WebSocket)
    → FastAPI → Retriever → LLM (+ ConversationStore)
    → Answer + cited sources; WebSocket streams tokens where applicable
```

---

## Repository Layout (What Lives Where)

```
├── config/settings.py       # Single Pydantic Settings; no raw os.environ in modules
├── src/
│   ├── main.py              # CLI: serve | worker | beat | ingest | query
│   ├── logging.py           # structlog
│   ├── drive/               # Drive auth (readonly), full_sync, incremental_sync, deletion detection
│   ├── storage/             # MinIO + local fallback (StorageBackend protocol)
│   ├── converter/           # FileConverter protocol, PDF/Docs/Sheets/Docx/Xlsx/Text + factory
│   ├── vectorizer/          # Chunker, BatchEmbedder, MilvusStore
│   ├── metadata/            # PostgreSQL: async repo (FastAPI) + sync repo (Celery)
│   ├── worker/              # Celery app, RetryableTask, tasks, sync DB helpers
│   ├── scheduler/           # Beat pipeline, distributed lock
│   ├── rag/                 # Retriever, LLM client, ConversationStore, RAG chain
│   ├── generator/         # SQLGenerator (+ safety), DBWriter, SheetsWriter
│   ├── automation/        # Engine + YAML templates
│   └── api/                 # FastAPI factory, routes, schemas, API key middleware
├── static/                  # Chatbot SPA (vanilla JS)
├── tests/                   # Mirrors src/ with test_ prefix
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── requirements-dev.txt
```

---

## Infrastructure (Docker Compose)

| Service | Port | Role |
|---------|------|------|
| **Redis** | 6379 | DB 0: Celery broker; DB 1: results; DB 2: retriever cache + conversation memory |
| **PostgreSQL** | 5432 | App metadata (`public`) + LLM-generated SQL output (`generated` + restricted user) |
| **Milvus** | 19530 | Vector index (e.g. HNSW, cosine) |
| **MinIO** | 9000/9001 | Blobs: raw uploads + converted text |
| **Ollama** | 11435→11434 | Embeddings/chat; on startup the container pulls `EMBED_MODEL` and `LLM_MODEL` from `.env` (or `OLLAMA_PULL_MODELS`). See `scripts/ollama-docker-entrypoint.sh`. |

---

## Configuration

- **Single source of truth:** `config/settings.py` (`Settings`), injected everywhere.
- **Precedence:** environment variables > `.env` > defaults. Use `SecretStr` for secrets.
- **Notable keys:** `database_url` / `database_url_sync` (Celery uses sync URL), isolated Redis URLs, `ollama_base_url`, embed/chat model names, `api_key` (empty disables auth), MinIO/Milvus hosts, optional `google_sheets_credentials` for Sheets writes.

---

## Architectural Patterns (Use Them, Do Not Fight Them)

| Pattern | Where | Why |
|---------|--------|-----|
| **Protocol** | `StorageBackend`, `FileConverter`, `LLMClient`, `VectorStore` | Testability + swap implementations |
| **Factory** | `get_converter`, `create_llm_client` | Add types without editing all call sites |
| **Chain** | Celery `download → convert → embed` | Scale stages independently |
| **Circuit breaker** | LLM client | Fail fast when upstream is unhealthy |
| **Repository** | Async + sync metadata repos | Same DB rules; Celery stays sync |
| **Distributed lock** | Incremental sync | No overlapping full/incremental runs |
| **Defense in depth** | SQL whitelist + restricted role + `generated` schema | LLM cannot destroy pipeline tables |

---

## Mandatory Principles

### TDD (Red–Green–Refactor)

1. **RED** — Add or extend a failing test that specifies the behavior.
2. **GREEN** — Implement the minimum code to pass.
3. **REFACTOR** — Clean up; keep tests green.

Run `pytest` after substantive changes. Do not skip failing tests to “move on.”

### SOLID

- **S**ingle responsibility per module.
- **O**pen/closed: extend via protocols/factories (e.g. new `FileConverter` without editing others).
- **L**iskov: implementations must honor protocol contracts.
- **I**nterface segregation: small Storage/LLM/DB surfaces.
- **D**ependency inversion: inject abstractions in constructors; no hidden globals.

### Code Quality

- Python 3.11+ type hints on public APIs; Pydantic for config and API bodies.
- `ruff check` + `ruff format` + `mypy --strict` on touched code paths.
- `async/await` for I/O; structured logging (`structlog`) with `request_id`, `file_id`, `task_name` where relevant.
- Retries with backoff and circuit breakers for external services.
- **All documentation and test names in English.**

### Environment

- Prefer **Docker Compose** for full stack parity; use a **venv** for local Python tooling and `pip install -r requirements-dev.txt`.

---

## Testing Conventions

- **Unit tests:** mock MinIO, Drive, Ollama, Milvus, Redis; pass mocks via DI.
- **Integration:** `@pytest.mark.integration` when real Docker services are required.
- **Browser E2E:** Playwright (`e2e/`) against a mock HTTP+WS server by default; optional `E2E_REAL_BASE_URL` smoke tests (`@smoke`).
- **Async:** `async def` tests; `asyncio_mode = "auto"` in `pyproject.toml`.
- **Fixtures:** `tests/conftest.py` — `settings`, `db_session`, mocks for external services, sample payloads.

---

## Common Commands

```bash
make install     # pip install -r requirements-dev.txt
make up          # docker compose up -d
make down        # docker compose down
make test        # pytest -v --tb=short
make e2e         # cd e2e && npm ci && npx playwright install chromium && npm run test:e2e
# Optional: E2E_REAL_BASE_URL=http://127.0.0.1:8000 npx playwright test --grep @smoke (from e2e/; real backend must be up). If Chromium fails to start on Linux, run once: npx playwright install --with-deps
make lint        # ruff check src/ tests/
make format      # ruff format src/ tests/
make typecheck   # mypy --strict src/
make clean       # docker compose down -v + remove __pycache__
```

---

## Definition of Done (Feature / Change)

- `pytest -v` green (no unintended skips/xfails).
- `mypy --strict src/` clean for changed modules.
- `ruff` clean.
- New behavior covered by tests where risk is non-trivial.
- Settings and secrets follow the existing `Settings` pattern; no new direct `os.environ` reads in library code.

---

## Operational Expectations (When Verifying the Whole System)

- `docker compose up -d` leaves all declared services healthy.
- Drive sync: first run can full-scan; later runs incremental; lock prevents concurrent sync races.
- Deleted Drive files trigger vector + object + metadata cleanup.
- Chat UI can stream answers and show sources; optional `X-API-Key` when `API_KEY` is set.
- `GET /status` reflects pipeline state where implemented.
