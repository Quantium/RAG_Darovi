# RAG Pipeline Application

A terabyte-scale document ingestion, vectorization, and LLM-powered analysis pipeline with multi-turn conversation memory, API authentication, and SQL safety guardrails.

> **Full plan details**: See [plans/PLAN_00_INDEX.md](plans/PLAN_00_INDEX.md) for the complete architecture, tech stack, project structure, and phase breakdown.

## Quick Reference

| Phase | File | Description |
|---|---|---|
| 1 | [PLAN_01_SETUP.md](plans/PLAN_01_SETUP.md) | Virtual environment, dependencies, Docker infrastructure |
| 2 | [PLAN_02_TDD_TESTS.md](plans/PLAN_02_TDD_TESTS.md) | Test infrastructure, conftest, and all test stubs (RED phase) |
| 3 | [PLAN_03_DOWNLOAD_CONVERT.md](plans/PLAN_03_DOWNLOAD_CONVERT.md) | Google Drive download and file conversion to text |
| 4 | [PLAN_04_CRON_SYNC.md](plans/PLAN_04_CRON_SYNC.md) | Celery workers, tasks, and scheduled incremental sync |
| 5 | [PLAN_05_EMBEDDING.md](plans/PLAN_05_EMBEDDING.md) | Batch embedding and vector storage in Milvus |
| 6 | [PLAN_06_LLM.md](plans/PLAN_06_LLM.md) | LLM client, retriever, SQL generator, and automation engine |
| 7 | [PLAN_07_UI_CHATBOT.md](plans/PLAN_07_UI_CHATBOT.md) | FastAPI + chatbot UI with document references |
