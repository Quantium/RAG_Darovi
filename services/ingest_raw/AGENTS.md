# AGENTS.md — ingest_raw

This file is the service-local guide for coding agents working in `services/ingest_raw`.

---

## Mission

`ingest_raw` is an isolated service responsible for:

- polling source documents from `drive` or `local`,
- detecting source changes via PostgreSQL metadata,
- uploading raw binaries to MinIO RAW bucket,
- updating RAW stage metadata in `file_records`.

---

## Non-negotiable boundaries

- Do not import modules from root `src/`.
- Do not import modules from sibling services.
- Integrate with other services using infrastructure contracts (PostgreSQL, MinIO), not Python imports.

---

## Engineering principles

- Follow TDD (Red → Green → Refactor).
- Apply SOLID principles.
- Keep docs and test names in English.
- Add/adjust tests for behavioral changes.

---

## Schema safety rule

Never change PostgreSQL schema (`file_records` or related tables) without explicitly alerting the requester first and confirming migration impact.

---

## Validation checklist

- Build from this folder only: `docker build ./services/ingest_raw`.
- Service startup works independently (`python main.py`).
- Cron run (`run_once`) updates RAW stage metadata deterministically.
- No hidden imports from root project modules.
