# rag-e2e-contracts

Cross-service validation repository for RAG Darovi.

## Scope

- End-to-end smoke tests for running service stacks.
- HTTP contract checks between `retrieval_admin` and `chatbot_response`.
- Schema contract checks against the shared PostgreSQL schema (`rag-schema`).

## Repository relationships

- **Orchestrated by:** `Quantium/RAG_Darovi` (`qa/rag-e2e-contracts` submodule path).
- **Validates service contracts for:** `Quantium/rag-service-retrieval-admin` and `Quantium/rag-service-chatbot-response`.
- **Validates schema compatibility with:** `Quantium/rag-schema`.
- **Runs against outputs produced upstream by:** `Quantium/rag-service-ingest-raw`, `Quantium/rag-service-extract-text`, and `Quantium/rag-legacy-core` where applicable.

## Prerequisites

- Local Docker stack up (from `rag-orchestrator`) with:
  - `retrieval-admin-service`
  - `chatbot-response-service`
  - `postgres`

## Run

```bash
make install
make smoke
make test
```

Environment overrides:

- `RETRIEVAL_ADMIN_BASE_URL` (default `http://localhost:8010`)
- `CHATBOT_RESPONSE_BASE_URL` (default `http://localhost:8020`)
- `DATABASE_DSN` (default `postgresql://postgres:postgres@localhost:5432/rag_darovi`)


```mermaid
flowchart LR
subgraph orchestratorRepo [OrchestratorRepo]
orchestrator[RAG_Darovi]
end

subgraph serviceRepos [ServiceRepos]
ingest[rag-service-ingest-raw]
extract[rag-service-extract-text]
retrieval[rag-service-retrieval-admin]
chatbot[rag-service-chatbot-response]
legacy[rag-legacy-core]
schema[rag-schema]
contracts[rag-e2e-contracts]
end

orchestrator --> ingest
orchestrator --> extract
orchestrator --> retrieval
orchestrator --> chatbot
orchestrator --> legacy
orchestrator --> schema
orchestrator --> contracts

ingest --> extract
ingest --> schema
extract --> schema
extract --> retrieval
retrieval --> schema
chatbot --> retrieval
legacy --> schema

contracts --> schema
contracts --> retrieval
contracts --> chatbot
contracts --> ingest
contracts --> extract
contracts --> legacy

```