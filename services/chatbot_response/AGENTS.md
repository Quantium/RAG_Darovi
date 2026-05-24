# AGENTS.md — chatbot_response

Service-local guide for coding agents.

## Mission

`chatbot_response` is an isolated chat service that:

- provides `/chat` and `/ws/chat`,
- manages conversation memory in Redis,
- calls `retrieval_admin` over HTTP for context retrieval,
- serves a minimal chat-only frontend.

## Non-negotiable boundaries

- Do not import modules from root `src/`.
- Do not import Python modules from sibling services.
- Use HTTP contract only for integration.

## Quality rules

- Follow TDD (red-green-refactor).
- Apply SOLID principles.
- Keep docs and tests in English.
- Add or update tests for all behavioral changes.

## Schema safety rule

Never change PostgreSQL schema (`file_records` or related tables) without explicitly alerting the requester first and confirming migration impact.

## Validation checklist

- Service builds from its own folder context.
- `/health` responds after startup.
- `/chat` and `/ws/chat` comply with service contract.
