# AGENTS.md (Orchestrator) - AI Agent Guide

This file is the canonical project briefing for coding agents working in the **orchestrator** repository (`Quantium/RAG_Darovi`). The platform is now split across multiple repositories. This repo no longer contains application code, only orchestration: Docker Compose, environment templates, gates, scripts, and documentation that ties the multi-repo system together.

For the deep architecture and behavior of each component, follow the `AGENTS.md` inside the corresponding submodule.

---

## What This Repository Is

The orchestrator runs the RAG Darovi platform locally via Docker Compose. It mounts every runtime as a git submodule:

| Submodule path | Source repository | Responsibility |
|---|---|---|
| `services/ingest_raw` | `Quantium/rag-service-ingest-raw` | RAW ingestion from Drive/local to MinIO |
| `services/extract_text` | `Quantium/rag-service-extract-text` | Text extraction from RAW into MinIO TEXT |
| `services/retrieval_admin` | `Quantium/rag-service-retrieval-admin` | Retrieval/admin API + simplified UI |
| `services/chatbot_response` | `Quantium/rag-service-chatbot-response` | Chat API + minimal chat UI |
| `dashboard/rag-dashboard-core` | `Quantium/rag-legacy-core` | Dashboard FastAPI + Celery monolith pending further decomposition |
| `schema/rag-schema` | `Quantium/rag-schema` | Shared Alembic migrations |
| `qa/rag-e2e-contracts` | `Quantium/rag-e2e-contracts` | Cross-service contracts and Playwright e2e |

The dashboard monolith image powers the `dashboard-api`, `dashboard-worker`, `dashboard-worker-vision`, `dashboard-beat` and `dashboard-qa` Compose services. The other Compose services build directly from their submodule path.

---

## Repository Layout

```
docker-compose.yml         # Orchestration entrypoint (build contexts point to submodules)
Makefile                   # Orchestrator-only targets
scripts/                   # Bootstrap and verification helpers
docs/repo-split/           # Split history, mapping and verification gates
.env.example               # Environment template for the full stack
production.env.example     # Production environment template
services/                  # Submodules: independent service repos
dashboard/rag-dashboard-core/  # Submodule: dashboard core
schema/rag-schema/         # Submodule: shared Alembic
qa/rag-e2e-contracts/      # Submodule: cross-service contracts
```

There is no `src/`, `tests/`, `config/` or `requirements.txt` in this repo: those moved to `dashboard/rag-dashboard-core` during the second cleanup.

---

## Mandatory Principles

- **Schema safety**: never change PostgreSQL schema (`file_records` or related tables) without alerting the requester first and confirming migration impact. Schema lifecycle lives in `rag-schema`.
- **Submodule discipline**: all changes to service code must happen inside the corresponding submodule's repo, then surface here as a submodule pointer bump.
- **Stable rollback baseline**: tag `v0.8.0` is the recovery anchor pre-split. See [docs/repo-split/VERIFICATION_GATES.md](docs/repo-split/VERIFICATION_GATES.md) for the rollback procedure.
- **Documentation in English** for all repos (matches the prior project rule).

---

## Verification Gates

Run from the orchestrator root:

| Target | What it does |
|--------|--------------|
| `make qa-dashboard` | Run dashboard core unit suite |
| `make qa-services` | Run unit suite of each service submodule |
| `make qa-cross` | Run cross-service contract tests (HTTP + schema) |
| `make qa-all` | All of the above in order |

Cross-service HTTP contracts require the Compose stack to be up (`make up`).

For end-to-end smoke after `make up`:

```bash
./scripts/verify-multi-repo-local.sh
```

---

## Operational Expectations

- `docker compose up -d` leaves all declared services healthy.
- `extract_text` produces text artifacts and updates metadata with only Postgres + MinIO running.
- `chatbot_response` answers while `ingest_raw` and `extract_text` are stopped, as long as retrieval dependencies are healthy.
- Submodule pointers are committed in the orchestrator and reproducible via `git submodule update --init --recursive`.

---

## Common Commands

```bash
make submodules     # git submodule sync + update
make up             # docker compose up -d
make down           # docker compose down
make docker-build   # docker compose build
make docker-qa      # dashboard core QA image
make qa-dashboard   # dashboard core unit tests
make qa-services    # all service unit tests
make qa-cross       # cross-service contracts
make qa-all         # all gates above
make tls-certs      # generate local TLS certs
make clean          # down -v + cleanup __pycache__
```

---

## Where to Make a Change

| Goal | Repo |
|------|------|
| Modify chat API behavior | `services/chatbot_response` |
| Modify retrieval logic | `services/retrieval_admin` |
| Modify text extraction | `services/extract_text` |
| Modify ingestion source | `services/ingest_raw` |
| Modify the dashboard worker / vision pipeline | `dashboard/rag-dashboard-core` |
| Add or change a DB migration | `schema/rag-schema` |
| Add cross-service contracts or e2e specs | `qa/rag-e2e-contracts` |
| Adjust orchestration (compose, env, scripts) | this repository |

If a change requires both a service code change and an orchestrator change (for example, a new env var), make the service change first, push it, and then bump the submodule pointer here.
