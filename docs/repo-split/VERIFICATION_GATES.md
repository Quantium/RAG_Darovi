# Multi-Repo Verification Gates

This document defines local verification gates for the multi-repo orchestrated setup.

## Stable baseline before separation

- Stable reference tag: `v0.8.0`.
- Use this tag as the recovery anchor if any separation phase introduces regressions.

## Legacy gate

Run from orchestrator root:

```bash
make qa-legacy
```

Expected:

- `legacy/rag-legacy-core`: full unit suite passes (185 tests, integration deselected).

## Service-level gates

Run from orchestrator root:

```bash
make qa-services
```

Expected:

- `services/ingest_raw`: tests pass.
- `services/extract_text`: tests pass.
- `services/retrieval_admin`: tests pass.
- `services/chatbot_response`: tests pass.

## Cross-service gates

Run from orchestrator root:

```bash
make qa-cross
```

Expected (with the local Compose stack running):

- `qa/rag-e2e-contracts` tests pass for:
  - retrieval/chatbot health contracts (`/health` endpoints reachable).
  - schema contract (`file_records` columns) against the orchestrated Postgres.

If the stack is not up, the HTTP contract tests will fail with `ConnectError` by design. Bring services up first with `make up` before running this gate.

## Full local gates

1. Start stack:

```bash
docker compose up -d --build
```

2. Run aggregate verification:

```bash
./scripts/verify-multi-repo-local.sh
```

3. Validate required tangible behaviors:

- `extract_text` produces text artifacts and updates metadata with only Postgres + MinIO dependencies.
- `chatbot_response` answers while `ingest_raw` and `extract_text` are stopped, as long as retrieval dependencies are healthy.

## Rollback to stable baseline (`v0.8.0`)

If a separation phase fails and you need to revert quickly:

```bash
git fetch --tags
git checkout v0.8.0
git submodule sync --recursive
git submodule update --init --recursive
```

If you need a recovery branch from that baseline:

```bash
git checkout -b rollback/v0.8.0
```

Recommended practice:

- Run rollback from a clean working tree or stash local changes first.
- After rollback, run the smoke checks and `./scripts/verify-multi-repo-local.sh`.
