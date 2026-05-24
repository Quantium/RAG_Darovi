# AGENTS.md — retrieval_admin

This file is the service-local guide for coding agents.

## Mission

`retrieval_admin` is an isolated FastAPI service responsible for:

- retrieval/context APIs consumed by `chatbot_response`,
- admin/status operational views,
- simplified non-chat frontend.

## Non-negotiable boundaries

- Do not import modules from root `src/`.
- Do not import Python modules from sibling services.
- Integration with other services must be over HTTP contracts only.

## Quality rules

- Follow TDD (red-green-refactor).
- Apply SOLID principles.
- Keep docs and tests in English.
- Add/adjust tests for every behavior change.

## Schema safety rule

Never change PostgreSQL schema (`file_records` or related tables) without explicitly alerting the requester first and confirming migration impact.

## Validation checklist

- Service can build with `docker build` using this folder as context.
- Service starts independently and serves `/health`.
- Contract endpoint (`/retrieve`) matches `API_CONTRACT.md`.
