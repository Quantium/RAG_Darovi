# RAG Darovi

A RAG (retrieval-augmented generation) pipeline: ingest documents from Google Drive or a local folder, convert and chunk text, embed with Ollama, store vectors in Milvus, and serve a FastAPI backend with a vanilla JS chat UI (REST + WebSocket), Celery workers, and PostgreSQL metadata. Optional API key auth and SQL automation features are included.

For architecture depth, phased build plans, and agent-oriented rules, see [AGENTS.md](AGENTS.md) and [PLAN.md](PLAN.md). The master index is [plans/PLAN_00_INDEX.md](plans/PLAN_00_INDEX.md).

## Table of contents

- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Local Python environment](#local-python-environment)
- [Run with Docker Compose](#run-with-docker-compose)
- [HTTPS (optional)](#https-optional)
- [Quality checks in Docker](#quality-checks-in-docker)
- [Makefile reference](#makefile-reference)
- [FAQ](#faq)

## Prerequisites

- **Docker Engine** and **Docker Compose v2** (`docker compose`, not the legacy `docker-compose` binary).
- **Git**.
- Roughly **~10 GB** free disk for images, volumes, and Ollama models (see [plans/PLAN_00_INDEX.md](plans/PLAN_00_INDEX.md)).
- **Python 3.11+** only if you run tests, linters, or the CLI on the host (not required to only use containers).
- **OpenSSL** if you generate TLS certificates with the provided script.

## Configuration

### Clone and `.env`

```bash
git clone <repository-url>
cd RAG_Darovi
cp .env.example .env
```

Edit `.env` as needed. The file is **gitignored**; never commit secrets.

### How settings are loaded

All application configuration goes through Pydantic **`Settings`** in [config/settings.py](config/settings.py):

- **Override order**: environment variables **>** `.env` file **>** code defaults.
- The model reads `.env` from the project root (`model_config` in `Settings`).

Compose services **`app-api`**, **`app-worker`**, and **`app-beat`** use `env_file: .env` plus an **`x-app-env`** block in [docker-compose.yml](docker-compose.yml) that sets **in-cluster hostnames** (`redis`, `postgres`, `milvus`, `minio`, `ollama`) so containers do not rely on `localhost` for other services. Your `.env` may still say `localhost` for **host-only** workflows; inside Compose, those URLs are overridden for the variables listed under `x-app-env`.

### Ingestion source

Choose the ingestion source with [`.env.example`](.env.example):

- `INGEST_SOURCE=drive` (default): use Google Drive credentials and folder selection.
- `INGEST_SOURCE=local`: read files recursively from `LOCAL_SOURCE_FOLDER`.

When using local mode, set `LOCAL_SOURCE_FOLDER` to an existing folder path visible to the process/container running the worker.

### Google Drive (optional)

For Drive sync, you need a Google **service account** JSON with Drive API access, placed under `credentials/` (see [`.env.example`](.env.example): `GOOGLE_APPLICATION_CREDENTIALS`, `DRIVE_FOLDER_ID`). The Docker image **does not** copy `credentials/` from the build context ([`.dockerignore`](.dockerignore)); for containers you must mount the directory or otherwise provide the file at the path referenced by `GOOGLE_APPLICATION_CREDENTIALS`.

### API key (optional)

If `API_KEY` is set in `.env`, clients must send header `X-API-Key`. Empty `API_KEY` disables auth (dev mode).

### LLM provider selection

The chat model is selected through `.env`:

- Local Ollama: `LLM_PROVIDER=ollama` with `LLM_BASE_URL` pointing to your Ollama OpenAI-compatible endpoint.
- DeepSeek API: `LLM_PROVIDER=deepseek`, set `DEEPSEEK_API_KEY`, and choose `LLM_MODEL` (for example `deepseek-chat`).

`DEEPSEEK_BASE_URL` defaults to `https://api.deepseek.com/v1/` and can be overridden if needed.

## Local Python environment

Use a virtual environment so dependencies stay isolated (aligned with [AGENTS.md](AGENTS.md)):

```bash
python3.11 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
```

Install dev dependencies (includes test and lint tools):

```bash
make install
# same as: pip install -r requirements-dev.txt
```

Production-only deps are listed in [requirements.txt](requirements.txt); dev/test extends them via [requirements-dev.txt](requirements-dev.txt). Tooling versions and pytest markers live in [pyproject.toml](pyproject.toml).

### Local quality commands

These match the project’s definition of done ([AGENTS.md](AGENTS.md)):

| Command | Purpose |
|--------|---------|
| `make test` | `pytest` with project defaults |
| `make lint` | `ruff check` on `src/` and `tests/` |
| `make format` | `ruff format` |
| `make typecheck` | `mypy --strict src/` |

### CLI entrypoint

The CLI is [src/main.py](src/main.py): `serve`, `worker`, `beat`, `ingest`, `query` (see [AGENTS.md](AGENTS.md) for overview).

## Run with Docker Compose

Build and start the stack:

```bash
docker compose up -d --build
# or: make up   # without --build; build first with make docker-build if needed
```

### Services (from [docker-compose.yml](docker-compose.yml))

| Service | Role |
|---------|------|
| `redis` | Celery broker, results, cache (logical DBs 0/1/2 via URLs) |
| `postgres` | Metadata and related SQL |
| `milvus-etcd` | Milvus dependency |
| `minio` | Object storage for raw/converted files |
| `milvus` | Vector store |
| `ollama` | Embeddings + LLM |
| `app-api` | FastAPI + static UI ([Dockerfile](Dockerfile)), default command [docker-entrypoint-api.sh](docker-entrypoint-api.sh) |
| `app-worker` | Celery worker |
| `app-beat` | Celery Beat scheduler |
| `app-qa` | **Profile `qa` only** — QA image ([Dockerfile.dev](Dockerfile.dev)), not started by default |

### Published ports (host)

| Port | Service |
|------|---------|
| **8000** | HTTP(S) API + static chat UI (`app-api`) |
| 5432 | PostgreSQL |
| 6379 | Redis |
| 9000, 9001 | MinIO API and console |
| 19530 | Milvus |
| **11435** | Ollama UI/API on the host (**container** listens on 11434; host **11435** avoids clashing with a local Ollama on **11434**) |

### Smoke checks

```bash
docker compose ps
curl -fsS http://localhost:8000/status
```

Open **http://localhost:8000** in a browser for the chat UI. WebSocket endpoint: **`/ws/chat`** (see [static/app.js](static/app.js)); REST **`GET /status`** is defined in [src/api/routes.py](src/api/routes.py).

### Logs

```bash
docker compose logs -f app-api
docker compose logs -f app-worker
```

### Healthcheck

`app-api` uses [docker-healthcheck-api.sh](docker-healthcheck-api.sh): HTTP or HTTPS to `127.0.0.1`:`API_PORT` **`/status`**, depending on TLS (see next section).

## HTTPS (optional)

For **local or LAN HTTPS** (e.g. to get a secure context for Web Crypto and `wss:`):

1. Generate a self-signed cert (OpenSSL):

   ```bash
   make tls-certs
   # or: ./scripts/generate-local-certs.sh ./certs
   ```

   Optional: **`TLS_SAN_HOSTS`** — comma-separated DNS names and IPs (defaults include `localhost`, `envidia`, `127.0.0.1` per [scripts/generate-local-certs.sh](scripts/generate-local-certs.sh)).

2. In `.env`, set (paths **inside** the `app-api` container match the compose volume):

   ```env
   API_SSL_CERTFILE=/etc/rag/certs/cert.pem
   API_SSL_KEYFILE=/etc/rag/certs/key.pem
   ```

   [docker-compose.yml](docker-compose.yml) mounts **`./certs:/etc/rag/certs:ro`** on `app-api`. [`.env.example`](.env.example) documents the same.

3. Restart `app-api`. The entrypoint enables uvicorn TLS when both files exist ([docker-entrypoint-api.sh](docker-entrypoint-api.sh)).

Browsers will warn on self-signed certs unless you trust them (e.g. import `cert.pem` or use [mkcert](https://github.com/FiloSottile/mkcert)).

## Quality checks in Docker

Run **ruff**, **mypy**, and **unit tests** (excludes integration) in a dedicated image without starting the full stack:

```bash
make docker-qa
```

Equivalent:

```bash
docker compose --profile qa build app-qa
docker compose --profile qa run --rm app-qa
```

[scripts/docker-qa.sh](scripts/docker-qa.sh) runs:

- `ruff check` / `ruff format --check` on `src/` and `tests/`
- `mypy --strict src/`
- `pytest -m "not integration"`

Tests marked **`integration`** in [pyproject.toml](pyproject.toml) expect real services (Milvus, MinIO, Ollama, etc.); run them separately when the stack is up if needed.

## Makefile reference

| Target | Description |
|--------|-------------|
| `make install` | `pip install -r requirements-dev.txt` |
| `make up` | `docker compose up -d` |
| `make down` | `docker compose down` |
| `make docker-build` | `docker compose build` |
| `make docker-qa` | Build and run `app-qa` (profile `qa`) |
| `make tls-certs` | `./scripts/generate-local-certs.sh ./certs` |
| `make test` | `pytest` |
| `make lint` | `ruff check` |
| `make format` | `ruff format` |
| `make typecheck` | `mypy --strict src/` |
| `make clean` | `docker compose down -v` and remove `__pycache__` |

## FAQ

### `permission denied` when talking to Docker

The Docker socket is often restricted to the **`docker`** group. Add your user: `sudo usermod -aG docker "$USER"` and **log out and back in**, or use `sudo docker compose ...` temporarily.

### Port 11434 already in use on the host

Compose maps the Ollama container to host port **11435** so a locally installed Ollama can keep **11434**. Pull models via the container, e.g. `docker compose exec ollama ollama pull nomic-embed-text` and `ollama pull llama3` (adjust service name if your project name differs).

### `crypto.randomUUID is not a function` in the browser

`crypto.randomUUID()` requires a **secure context** (HTTPS or `http://localhost`). On plain HTTP to another hostname, use **HTTPS** (see [HTTPS (optional)](#https-optional)) or rely on the **`randomUUID()` fallback** in [static/app.js](static/app.js).

### WebSocket fails

The UI builds **`ws:` / `wss:`** from `location` ([static/app.js](static/app.js)). Use the same host and port as the API; with HTTPS, the page should load over **HTTPS** so the socket uses **wss:**.

### `app-api` unhealthy

Check `docker compose logs app-api`, verify dependencies reached **healthy**, and that **`/status`** responds. With TLS, the healthcheck uses HTTPS with `-k` ([docker-healthcheck-api.sh](docker-healthcheck-api.sh)).

### Drive sync does nothing

Confirm **service account JSON** path, **`DRIVE_FOLDER_ID`**, and API enablement. Mount `credentials/` into the container if you run sync inside Docker.

### Local sync does nothing

Set `INGEST_SOURCE=local` and verify `LOCAL_SOURCE_FOLDER` points to a real directory accessible by the worker process/container.

### Where are production vs dev dependencies?

- **Runtime image** ([Dockerfile](Dockerfile)): [requirements.txt](requirements.txt) only.
- **QA image** ([Dockerfile.dev](Dockerfile.dev)): [requirements-dev.txt](requirements-dev.txt).
