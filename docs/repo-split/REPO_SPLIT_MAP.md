# Repository Split Map

This document maps current project paths to the target multi-repository layout.

## Target repositories

- `rag-orchestrator` (this repository)
- `rag-service-ingest-raw`
- `rag-service-extract-text`
- `rag-service-retrieval-admin`
- `rag-service-chatbot-response`
- `rag-schema`
- `rag-e2e-contracts`
- `rag-legacy-core` (second cleanup target for the remaining monolith runtime)

## Decisions log

- `e2e/` will live in `qa/rag-e2e-contracts` (Option A from the second cleanup plan). It already runs against an isolated mock backend and aligns with the cross-service QA charter; over time it will be expanded to cover `retrieval_admin` and `chatbot_response` UIs.

## Source-to-target mapping

### rag-service-ingest-raw

- `services/ingest_raw/**`
- `tests/test_services/test_ingest_raw_service.py`

### rag-service-extract-text

- `services/extract_text/**`
- `tests/test_services/test_extract_text_service.py`

### rag-service-retrieval-admin

- `services/retrieval_admin/**`
- `tests/test_services/test_retrieval_admin_service.py`

### rag-service-chatbot-response

- `services/chatbot_response/**`
- `tests/test_services/test_chatbot_response_service.py`
- `tests/test_services/test_chatbot_contract.py` (consumer-side unit contract checks)

### rag-schema

- Schema model references from `src/metadata/repository.py`
- Operational schema contract references:
  - `services/ingest_raw/app/db.py`
  - `services/extract_text/app/db.py`
- New Alembic structure will become source of truth:
  - `alembic.ini`
  - `alembic/env.py`
  - `alembic/versions/*.py`

### rag-e2e-contracts

- `tests/test_services/test_schema_contract.py`
- `tests/test_services/test_service_isolation.py`
- `e2e/**` (migrated incrementally, starting with smoke-focused suites)
- Cross-service Docker smoke and contract harness files created in this split.

### rag-orchestrator

Keep:

- `docker-compose.yml` (refactored to submodule build contexts)
- `README.md`, `.env.example`/`production.env.example`, operational scripts
- Root-level bootstrap and helper scripts
- Optional legacy `src/` stack while transition is in progress

Remove from this repository after extraction:

- `services/*` source directories (replaced by submodules)
- `tests/test_services/*` tests moved to service repos or `rag-e2e-contracts`

### rag-legacy-core (second cleanup)

Receives the remaining monolith runtime currently sitting at the orchestrator root:

- `src/`
- `tests/`
- `config/`
- `static/`
- `Dockerfile`, `Dockerfile.dev`
- `docker-entrypoint-api.sh`, `docker-healthcheck-api.sh`
- `requirements.txt`, `requirements-dev.txt`
- `pyproject.toml`
