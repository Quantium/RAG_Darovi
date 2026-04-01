# Phase 1: Environment Setup & Infrastructure

**Goal**: Create the Python virtual environment, install all dependencies, scaffold the project directory structure, and bring up the Docker infrastructure.

**Depends on**: Nothing (first phase).

**Success Criteria**: `docker compose up -d` starts all services healthy; `python -c "from config.settings import Settings; print(Settings())"` succeeds inside the venv; `python -c "import src"` succeeds.

---

## Step 1.1 — Python Virtual Environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

Verify: `python --version` → `3.11.x`.

---

## Step 1.2 — Dependencies

Create **two** requirements files to keep the production image lean.

### `requirements.txt` (production)

```
# Core
fastapi>=0.111,<1
uvicorn[standard]>=0.30,<1
pydantic>=2.7,<3
pydantic-settings>=2.3,<3

# Google Drive
google-api-python-client>=2.134,<3
google-auth>=2.30,<3
gspread>=6.1,<7

# PDF + OCR
pdfplumber>=0.11,<1
pytesseract>=0.3.10,<1
pdf2image>=1.17,<2

# Additional file formats
python-docx>=1.1,<2
openpyxl>=3.1,<4
beautifulsoup4>=4.12,<5
markdown>=3.6,<4

# Tokenization (chunker)
tiktoken>=0.7,<1

# Embeddings + Vector DB
pymilvus>=2.4,<3

# Database
sqlalchemy[asyncio]>=2.0,<3
asyncpg>=0.29,<1
psycopg2-binary>=2.9,<3

# Task Queue
celery[redis]>=5.4,<6
redis>=5.0,<6

# Object Storage
minio>=7.2,<8

# LLM (OpenAI-compatible client)
openai>=1.35,<2

# Automation configs
pyyaml>=6.0,<7

# HTTP client (embedder, healthchecks)
httpx>=0.27,<1

# Observability
structlog>=24.4,<25
```

> **Note on `psycopg2-binary`**: Required because Celery tasks run synchronously and cannot use `asyncpg`. Celery's result backend and certain metadata queries use this driver.

### `requirements-dev.txt` (dev/test — extends production)

```
-r requirements.txt

# Test
pytest>=8.2,<9
pytest-asyncio>=0.23,<1
pytest-cov>=5.0,<6
aiosqlite>=0.20,<1
httpx-ws>=0.6,<1

# Linting & Formatting (ruff replaces black for formatting via `ruff format`)
ruff>=0.5,<1
mypy>=1.10,<2
```

Install (development):

```bash
pip install -r requirements-dev.txt
```

---

## Step 1.3 — .env.example

Create `.env.example` with all environment variables the project uses. This serves as documentation and template.

```env
# Google Drive (read-only scope)
GOOGLE_APPLICATION_CREDENTIALS=credentials/service-account.json
DRIVE_FOLDER_ID=

# Google Sheets (write scope — can reuse the same SA JSON if granted sheets scope)
GOOGLE_SHEETS_CREDENTIALS=credentials/service-account.json

# MinIO
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_SECURE=false
MINIO_BUCKET_RAW=raw-files
MINIO_BUCKET_TEXT=converted-texts

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/rag_darovi
DATABASE_URL_SYNC=postgresql+psycopg2://postgres:postgres@localhost:5432/rag_darovi

# Redis (separate DBs to isolate broker, results, and cache)
REDIS_BROKER_URL=redis://localhost:6379/0
REDIS_RESULT_URL=redis://localhost:6379/1
REDIS_CACHE_URL=redis://localhost:6379/2

# Milvus
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=rag_documents

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
EMBED_MODEL=nomic-embed-text
EMBED_DIM=768
EMBED_BATCH_SIZE=64

# LLM
LLM_PROVIDER=ollama
LLM_MODEL=llama3
LLM_API_KEY=
LLM_BASE_URL=http://localhost:11434/v1/

# Scheduler
SYNC_INTERVAL_HOURS=24

# API
API_HOST=0.0.0.0
API_PORT=8000
API_KEY=
```

Copy it: `cp .env.example .env` and fill in real values.

---

## Step 1.4 — .gitignore

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
dist/
build/

# Environment
.env

# Credentials
credentials/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# Docker volumes
docker-data/
```

---

## Step 1.4b — .dockerignore

Prevents copying unnecessary files into the Docker build context:

```dockerignore
.venv/
.git/
.env
credentials/
docker-data/
__pycache__/
*.pyc
*.pyo
*.egg-info/
tests/
plans/
.DS_Store
Thumbs.db
.idea/
.vscode/
.cursor/
*.md
!requirements*.txt
```

---

## Step 1.5 — config/settings.py

Pydantic Settings class that reads from `.env`. Sensitive fields use `SecretStr` to prevent accidental logging:

```python
from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Google Drive (read-only)
    google_application_credentials: str = "credentials/service-account.json"
    drive_folder_id: str = ""

    # Google Sheets (write — may share the same SA file)
    google_sheets_credentials: str = "credentials/service-account.json"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: SecretStr = SecretStr("minioadmin")
    minio_secret_key: SecretStr = SecretStr("minioadmin")
    minio_secure: bool = False
    minio_bucket_raw: str = "raw-files"
    minio_bucket_text: str = "converted-texts"

    # PostgreSQL (async for FastAPI, sync for Celery tasks)
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_darovi"
    )
    database_url_sync: SecretStr = SecretStr(
        "postgresql+psycopg2://postgres:postgres@localhost:5432/rag_darovi"
    )

    # Redis (isolated DBs: broker=0, results=1, cache=2)
    redis_broker_url: str = "redis://localhost:6379/0"
    redis_result_url: str = "redis://localhost:6379/1"
    redis_cache_url: str = "redis://localhost:6379/2"

    # Milvus
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "rag_documents"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    embed_model: str = "nomic-embed-text"
    embed_dim: int = 768
    embed_batch_size: int = 64

    # LLM
    llm_provider: str = "ollama"
    llm_model: str = "llama3"
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "http://localhost:11434/v1/"

    # Scheduler
    sync_interval_hours: int = 24

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_key: SecretStr = SecretStr("")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

> **Note**: Use `.get_secret_value()` to extract the actual string from `SecretStr` fields when passing them to clients (e.g., `settings.minio_access_key.get_secret_value()`). This prevents credentials from appearing in logs or tracebacks.

---

## Step 1.6 — Directory Scaffold

Create all directories and `__init__.py` files:

```bash
mkdir -p config src/{drive,storage,converter,vectorizer,metadata,worker,rag,generator,automation,api,scheduler}
mkdir -p tests/{test_config,test_drive,test_storage,test_converter,test_vectorizer,test_metadata,test_worker,test_scheduler,test_rag,test_generator,test_automation,test_api}
mkdir -p credentials static

touch config/__init__.py
touch src/__init__.py
touch src/{drive,storage,converter,vectorizer,metadata,worker,rag,generator,automation,api,scheduler}/__init__.py
touch tests/__init__.py
touch tests/{test_config,test_drive,test_storage,test_converter,test_vectorizer,test_metadata,test_worker,test_scheduler,test_rag,test_generator,test_automation,test_api}/__init__.py
```

> **Note**: `config/__init__.py` is required so that `from config.settings import Settings` works. `static/` hosts the chatbot SPA created in Phase 7.

---

## Step 1.7 — Dockerfile

Multi-stage build to keep the production image lean (dev/test dependencies excluded):

```dockerfile
# --- Stage 1: Install Python dependencies ---
FROM python:3.11-slim AS builder

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Stage 2: Production image ---
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app
COPY . .

EXPOSE 8000

CMD ["uvicorn", "src.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

> **Note**: `curl` is required for container healthchecks. Only `requirements.txt` (production) is installed — dev/test tools stay out of the image. The `.dockerignore` (Step 1.4b) prevents `.venv/`, `tests/`, credentials, etc. from entering the build context.

---

## Step 1.8 — docker-compose.yml

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 5

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: rag_darovi
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      retries: 5

  milvus-etcd:
    image: bitnami/etcd:3.5
    environment:
      ALLOW_NONE_AUTHENTICATION: "yes"
      ETCD_ADVERTISE_CLIENT_URLS: "http://milvus-etcd:2379"
    healthcheck:
      test: ["CMD", "etcdctl", "endpoint", "health"]
      interval: 10s
      retries: 5

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - miniodata:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 10s
      retries: 5

  milvus:
    image: milvusdb/milvus:v2.4-latest
    command: ["milvus", "run", "standalone"]
    environment:
      ETCD_ENDPOINTS: milvus-etcd:2379
      MINIO_ADDRESS: minio:9000
    ports:
      - "19530:19530"
    volumes:
      - milvusdata:/var/lib/milvus
    depends_on:
      milvus-etcd:
        condition: service_healthy
      minio:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9091/healthz"]
      interval: 10s
      retries: 10

  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_models:/root/.ollama
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 10s
      retries: 5

  app-api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      milvus:
        condition: service_healthy
      ollama:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/status"]
      interval: 10s
      retries: 5

  app-worker:
    build: .
    command: celery -A src.worker.celery_app worker --loglevel=info --concurrency=4
    env_file: .env
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy

  app-beat:
    build: .
    command: celery -A src.worker.celery_app beat --loglevel=info
    env_file: .env
    depends_on:
      redis:
        condition: service_healthy

volumes:
  pgdata:
  miniodata:
  milvusdata:
  ollama_models:
```

---

## Step 1.9 — Makefile

Standardize common commands to avoid re-typing:

```makefile
.PHONY: up down test lint format install clean

install:
	pip install -r requirements-dev.txt

up:
	docker compose up -d

down:
	docker compose down

test:
	pytest -v --tb=short

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

typecheck:
	mypy --strict src/

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} +
```

---

## Step 1.10 — Verification Checklist

| # | Check | Command |
|---|---|---|
| 1 | Venv active | `which python` → `.venv/bin/python` |
| 2 | Deps installed | `pip check` → no broken dependencies |
| 3 | Config import works | `python -c "from config.settings import Settings; print(Settings())"` |
| 4 | Src import works | `python -c "import src"` |
| 5 | Infra up | `docker compose up -d` → all services healthy |
| 6 | Redis reachable | `docker compose exec redis redis-cli ping` → `PONG` |
| 7 | Postgres reachable | `docker compose exec postgres pg_isready` → accepting connections |
| 8 | Milvus reachable | `curl http://localhost:19530/v1/vector/collections` |
| 9 | MinIO reachable | `curl http://localhost:9000/minio/health/live` |
| 10 | Ollama reachable | `curl http://localhost:11434/api/tags` |

---

## Output of This Phase

- `.venv/` with all dependencies
- `requirements.txt` (production), `requirements-dev.txt` (dev/test)
- `.env.example`, `.env`, `.gitignore`, `.dockerignore`
- `config/__init__.py`, `config/settings.py` (with `SecretStr` for sensitive fields)
- Full directory scaffold with all `__init__.py` files (including `static/`)
- `Dockerfile` (multi-stage), `docker-compose.yml` (all services with healthchecks + persistent volumes)
- `Makefile` for standardized commands
- All Docker services running and healthy
