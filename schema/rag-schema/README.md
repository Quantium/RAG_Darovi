# rag-schema

Shared Alembic migrations repository for RAG Darovi services.

## Scope

- Owns PostgreSQL schema lifecycle for shared tables:
  - `file_records`
  - `sync_state`
  - `drive_connection`
  - `extracted_documents`
- Acts as the single source of truth for schema evolution used by:
  - ingest_raw
  - extract_text
  - retrieval_admin
  - chatbot_response (indirectly through retrieval contracts)

## Repository relationships

- **Orchestrated by:** `Quantium/RAG_Darovi` (`schema/rag-schema` submodule path).
- **Direct consumers:** `Quantium/rag-service-ingest-raw`, `Quantium/rag-service-extract-text`, `Quantium/rag-service-retrieval-admin`, and `Quantium/rag-legacy-core`.
- **Indirect consumer:** `Quantium/rag-service-chatbot-response` through retrieval dependencies.
- **Contract verification:** `Quantium/rag-e2e-contracts` validates schema contract consistency.

## Quick start

```bash
make install
make db-upgrade
make db-current
```

`alembic.ini` defaults to local postgres:

`postgresql+psycopg2://postgres:postgres@localhost:5432/rag_darovi`

Override using:

```bash
ALEMBIC_CONFIG=alembic.ini .venv/bin/alembic -x sqlalchemy.url=...
```


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

