# AGENTS.md — extract_text

This file is the service-local guide for coding agents working in `services/extract_text`.

---

## Mission

`extract_text` is an isolated service responsible for:

- polling PostgreSQL for RAW changes,
- enforcing singleton extraction runs with PostgreSQL advisory lock,
- reading RAW objects from MinIO,
- extracting normalized text by MIME type,
- writing text artifacts to MinIO TEXT bucket,
- updating text stage metadata in `file_records`.

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

- Build from this folder only: `docker build ./services/extract_text`.
- Service startup works independently (`python main.py`).
- Locking behavior prevents concurrent extraction runs.
- Text stage updates (`ready_for_embedding` / `failed`) are deterministic.
- No hidden imports from root project modules.
