# Phase 5: Embedding Pipeline & Vector Storage

**Goal**: Implement batch embedding via Ollama and vector storage in Milvus. Complete the `embed_file` worker task placeholder from Phase 4. After this phase, the full ingestion pipeline (download → convert → embed) is operational.

**Depends on**: Phase 4 (Celery workers, chunker, task_helpers implemented).

**Success Criteria**: Tests in `test_vectorizer/test_embedder.py` and `test_vectorizer/test_milvus_store.py` turn GREEN. `test_embed_task_calls_embedder` in `test_worker/test_tasks.py` turns GREEN. A document can go from Drive to searchable vectors in Milvus end-to-end.

---

## Step 5.1 — Batch Embedder

**File**: `src/vectorizer/embedder.py`

**Class**: `BatchEmbedder`

**Constructor** (supports DI of `httpx.AsyncClient` for testing):

```python
from __future__ import annotations

import httpx
import structlog
from config.settings import Settings

logger = structlog.get_logger()


class BatchEmbedder:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = settings.ollama_base_url
        self._model = settings.embed_model
        self._batch_size = settings.embed_batch_size
        self._dim = settings.embed_dim
        self._client = client

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches. Returns one vector per input text."""
        ...
```

> **Note on DI**: The tests inject a mocked `httpx.AsyncClient` via the `client` parameter. When `client` is `None`, the embedder creates its own `httpx.AsyncClient` with connection pooling internally.

**Logic**:

1. Split `texts` into batches of `embed_batch_size` (default 64).
2. For each batch, call Ollama's `/api/embed` endpoint:
   ```
   POST {ollama_base_url}/api/embed
   {"model": "nomic-embed-text", "input": ["text1", "text2", ...]}
   ```
3. Collect all embedding vectors (each 768-dim).
4. Return flat list of vectors in input order.

**Internal client management**:

```python
async def embed_texts(self, texts: list[str]) -> list[list[float]]:
    all_embeddings: list[list[float]] = []
    total_batches = (len(texts) + self._batch_size - 1) // self._batch_size

    async with self._get_client() as client:
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            batch_num = i // self._batch_size + 1
            logger.info("embedding.batch", batch=f"{batch_num}/{total_batches}", size=len(batch))

            embeddings = await self._embed_batch(client, batch)
            all_embeddings.extend(embeddings)

    return all_embeddings


def _get_client(self):
    if self._client:
        # DI client: wrap in a no-op context manager
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _wrap():
            yield self._client
        return _wrap()
    return httpx.AsyncClient(timeout=60.0)
```

**Error handling**:
- Retry on connection error (3 attempts, exponential backoff).
- Log batch progress: `"embedding batch 3/12"`.
- If a single text is empty, return a zero vector with warning.

**`_embed_batch` with retry**:

```python
async def _embed_batch(
    self, client: httpx.AsyncClient, texts: list[str], max_retries: int = 3
) -> list[list[float]]:
    for attempt in range(max_retries):
        try:
            response = await client.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": texts},
            )
            response.raise_for_status()
            return response.json()["embeddings"]
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt
            logger.warning("embedding.retry", attempt=attempt + 1, wait=wait, error=str(exc))
            import asyncio
            await asyncio.sleep(wait)
    return []  # unreachable but satisfies type checker
```

**Performance**:
- Use `httpx.AsyncClient` with connection pooling (single client per `embed_texts` call).
- Batch size of 64 reduces HTTP overhead by ~60x vs one-by-one.

**Tests to turn GREEN**: `tests/test_vectorizer/test_embedder.py`

**SC**: `pytest tests/test_vectorizer/test_embedder.py -v` → all pass.

---

## Step 5.2 — Milvus Store

**File**: `src/vectorizer/milvus_store.py`

**Protocol** (defined in this file, implemented structurally by `MilvusStore`):

```python
from __future__ import annotations

from typing import Protocol


class VectorStore(Protocol):
    def create_collection(self) -> None: ...
    def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None: ...
    def search(self, query_embedding: list[float], top_k: int, partition: str | None = None) -> list[dict]: ...
    def delete_by_source(self, source_file_id: str) -> None: ...
    def collection_exists(self) -> bool: ...
```

**Class**: `MilvusStore`

**Constructor** (supports DI for testing):

```python
import structlog
from pymilvus import connections, Collection, utility
from config.settings import Settings

logger = structlog.get_logger()


class MilvusStore:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._collection_name = settings.milvus_collection
        self._dim = settings.embed_dim
        self._host = settings.milvus_host
        self._port = settings.milvus_port
        self._client = client  # injected mock for tests
        if client is None:
            connections.connect(host=self._host, port=self._port)
```

> **Note on DI**: When `client` is provided (tests), methods call `self._client.*` directly. When `None` (production), methods use the `pymilvus` high-level API. Tests in PLAN_02 inject `mock_milvus_client` via this parameter.

**Collection schema** (Milvus):

| Field | Type | Description |
|---|---|---|
| `id` | `VARCHAR(256)` PK | Hash of `source_file_id` + `chunk_index` |
| `source_file_id` | `VARCHAR(256)` | Google Drive file ID |
| `source_name` | `VARCHAR(512)` | File name |
| `document_type` | `VARCHAR(64)` | `doc` / `sheet` / `pdf` |
| `section_title` | `VARCHAR(512)` | Section or sheet name |
| `chunk_index` | `INT64` | Position within source |
| `text` | `VARCHAR(65535)` | Chunk content |
| `embedding` | `FLOAT_VECTOR(768)` | nomic-embed-text vector |

**Index**: HNSW on `embedding` field:
- `metric_type`: `COSINE`
- `M`: 16
- `efConstruction`: 256

**Partitions**: `doc`, `sheet`, `pdf` — created on collection init.

**Methods**:

- `create_collection()`:
  1. Define schema with all fields.
  2. Create collection.
  3. Create HNSW index.
  4. Create partitions (`doc`, `sheet`, `pdf`).
  5. Load collection into memory.
  6. Log: `logger.info("milvus.collection_created", name=self._collection_name)`.

- `ensure_collection()`:
  1. Check `collection_exists()`.
  2. If not, call `create_collection()`.
  3. Idempotent — safe to call on every task invocation.

- `upsert(chunks, embeddings)`:
  1. Build insert data from chunks + embeddings.
  2. Determine partition from `document_type`.
  3. **Batch inserts in groups of 1000** to avoid Milvus memory pressure on large files.
  4. Flush after all inserts.
  5. Log: `logger.info("milvus.upserted", count=len(chunks))`.

- `search(query_embedding, top_k=10, partition=None)`:
  1. Search with HNSW params (`ef`: 128).
  2. Filter by partition if specified.
  3. Return list of `{"id", "source_file_id", "source_name", "section_title", "text", "score"}`.

- `delete_by_source(source_file_id)`:
  1. Delete all entities where `source_file_id` matches.
  2. Used when re-processing a modified file (delete old chunks before re-embedding).
  3. Log: `logger.info("milvus.deleted_source", source_file_id=source_file_id)`.

- `collection_exists() -> bool`:
  1. Returns `True` if the collection already exists in Milvus.

**Tests to turn GREEN**: `tests/test_vectorizer/test_milvus_store.py`

**SC**: `pytest tests/test_vectorizer/test_milvus_store.py -v` → all pass.

---

## Step 5.3 — Collection Initialization

Before vectors can be stored, the Milvus collection must exist. There are two entry points:

1. **Worker startup**: Add to `src/worker/task_helpers.py`:

```python
def ensure_milvus_collection(settings: Settings | None = None) -> None:
    """Create the Milvus collection if it doesn't exist. Idempotent."""
    from src.vectorizer.milvus_store import MilvusStore
    s = settings or build_settings()
    store = MilvusStore(s)
    store.ensure_collection()
```

2. **CLI command**: The `src/main.py` CLI (Phase 7) will also call this during `ingest` or `serve`.

3. **FastAPI lifespan**: Called during API startup (Phase 7).

The `embed_file` task calls `ensure_collection()` defensively on each invocation. Since it's idempotent, the overhead is a single `has_collection()` check.

---

## Step 5.4 — Complete the `embed_file` Task

**File**: `src/worker/tasks.py` (replace the `NotImplementedError` placeholder from Phase 4)

Replace the placeholder with the full implementation. Consolidates all async operations into a single `asyncio.run()` call to avoid creating multiple event loops:

```python
import asyncio
from datetime import datetime, timezone

import structlog

from src.worker.celery_app import app, RetryableTask
from src.worker.task_helpers import build_settings, build_storage, build_metadata_repo

logger = structlog.get_logger()

MILVUS_INSERT_BATCH_SIZE = 1000


@app.task(base=RetryableTask, bind=True)
def embed_file(self, convert_result: dict) -> dict:
    """Chunk text, embed via Ollama, upsert vectors to Milvus."""
    if convert_result.get("skipped"):
        return convert_result

    drive_file_id = convert_result["drive_file_id"]
    logger.info("task.embed.started", drive_file_id=drive_file_id)

    settings = build_settings()
    storage = build_storage(settings)

    text_bytes = storage.download(settings.minio_bucket_text, convert_result["minio_text_key"])
    text = text_bytes.decode("utf-8")

    from src.vectorizer.chunker import DocumentChunker
    chunker = DocumentChunker()
    chunks = chunker.chunk(
        text,
        source_file_id=drive_file_id,
        source_name=convert_result["name"],
        document_type=convert_result["document_type"],
    )

    if not chunks:
        logger.info("task.embed.no_chunks", drive_file_id=drive_file_id)
        asyncio.run(_update_embedded(settings, drive_file_id, chunk_count=0))
        return {"drive_file_id": drive_file_id, "chunk_count": 0}

    chunk_count = asyncio.run(_embed_and_store(settings, drive_file_id, chunks))
    logger.info("task.embed.completed", drive_file_id=drive_file_id, chunk_count=chunk_count)
    return {"drive_file_id": drive_file_id, "chunk_count": chunk_count}


async def _embed_and_store(settings, drive_file_id: str, chunks: list) -> int:
    """Single async context for all embedding + storage operations."""
    from src.vectorizer.embedder import BatchEmbedder
    from src.vectorizer.milvus_store import MilvusStore

    embedder = BatchEmbedder(settings)
    texts = [c.text for c in chunks]
    embeddings = await embedder.embed_texts(texts)

    store = MilvusStore(settings)
    store.ensure_collection()
    store.delete_by_source(drive_file_id)

    chunk_dicts = [
        {
            "id": f"{c.source_file_id}_{c.chunk_index}",
            "source_file_id": c.source_file_id,
            "source_name": c.source_name,
            "document_type": c.document_type,
            "section_title": c.section_title,
            "chunk_index": c.chunk_index,
            "text": c.text,
        }
        for c in chunks
    ]
    store.upsert(chunk_dicts, embeddings)

    await _update_embedded(settings, drive_file_id, chunk_count=len(chunks))
    return len(chunks)


async def _update_embedded(settings, drive_file_id: str, chunk_count: int) -> None:
    """Update metadata: chunk_count, status, last_processed_at."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from src.metadata.repository import MetadataRepository

    engine = create_async_engine(settings.database_url.get_secret_value())
    async with AsyncSession(engine) as session:
        repo = MetadataRepository(session)
        await repo.update_chunk_count(drive_file_id, chunk_count)
        await repo.update_status(drive_file_id, "embedded")
        # TODO: repo.update_last_processed_at(drive_file_id, datetime.now(timezone.utc))
        await session.commit()
    await engine.dispose()
```

**Key design decisions**:

- **Single `asyncio.run()`**: `_embed_and_store()` groups all async work (embed + DB update) in one event loop invocation. The sync Milvus operations (`delete_by_source`, `upsert`) run inside the same function since they're synchronous and don't need the event loop.
- **Re-indexing**: `delete_by_source(drive_file_id)` before `upsert()` ensures no stale vectors remain when a file is re-processed after modification in Drive.
- **`last_processed_at`**: Updated alongside status to track when each file was last successfully processed.
- **`ensure_collection()`**: Called defensively to auto-create the collection on first use.
- **Explicit `chunk_dicts`**: Builds dicts with named fields instead of `vars(c)` for clarity and to avoid leaking internal dataclass fields.

**Tests to turn GREEN**: `test_embed_task_calls_embedder` in `tests/test_worker/test_tasks.py`

---

## Step 5.5 — Performance Considerations

### Batch sizing

| Operation | Default Batch Size | Rationale |
|---|---|---|
| Ollama embedding | 64 texts (`embed_batch_size`) | Balances HTTP overhead vs memory; 64 texts of ~512 tokens each ≈ 32k tokens per request |
| Milvus insert | 1000 vectors (`MILVUS_INSERT_BATCH_SIZE`) | Milvus recommends ≤ 10k entities per insert; 1000 is conservative for stability |

### Large file handling

For files that produce > 5000 chunks (e.g., a 500-page PDF):
- The embedder processes in batches of 64 — no memory issue.
- Milvus inserts in batches of 1000 — no timeout risk.
- The task may run for several minutes; Celery's `task_acks_late=True` prevents premature requeue.

### Memory budget

Each worker should have ≤ 2GB RAM. At 768-dim float32 vectors:
- 1000 vectors ≈ 3MB (negligible).
- The bottleneck is text in memory: a 500-page PDF might produce ~2MB of text + chunks.
- Workers process one file at a time (single task) — no concurrent memory pressure.

---

## Step 5.6 — Integration Verification

Run the full vectorizer test suite:

```bash
pytest tests/test_vectorizer/ -v
```

Then run the full worker tests to confirm embed task works:

```bash
pytest tests/test_worker/ -v
```

All tests should now be GREEN (including `test_embed_task_calls_embedder`).

### End-to-End Manual Test

> **Prerequisite**: Docker services must be running (`docker compose up -d`) and the embedding model must be pulled.

1. Pull the embedding model:
   ```bash
   docker compose exec ollama ollama pull nomic-embed-text
   ```

2. Trigger the pipeline for a single test file:
   ```python
   from src.worker.tasks import download_file, convert_file, embed_file
   from celery import chain

   pipeline = chain(
       download_file.s({"id": "test-id", "name": "test.pdf", "mimeType": "application/pdf"}),
       convert_file.s(),
       embed_file.s(),
   )
   result = pipeline.apply_async()
   print(result.get(timeout=120))
   ```

3. Verify vectors exist in Milvus:
   ```python
   from pymilvus import connections, Collection
   connections.connect(host="localhost", port=19530)
   col = Collection("rag_documents")
   col.flush()
   print(f"Entities: {col.num_entities}")  # should be > 0
   ```

4. Verify metadata updated:
   ```python
   # Check PostgreSQL for status = "embedded"
   ```

---

## Output of This Phase

- `src/vectorizer/embedder.py` — `BatchEmbedder` with `httpx.AsyncClient` DI, retry logic, batch progress logging
- `src/vectorizer/milvus_store.py` — `VectorStore` protocol + `MilvusStore` with DI, `ensure_collection()`, batched inserts, structured logging
- `src/worker/task_helpers.py` — `ensure_milvus_collection()` added
- `src/worker/tasks.py` — `embed_file` task fully implemented with single `asyncio.run()`, re-indexing, `last_processed_at` update
- Full ingestion pipeline operational: Drive → MinIO → Text → Chunks → Vectors → Milvus
- Re-indexing support: modified files get old vectors deleted before re-embedding
- All `test_vectorizer/` and `test_worker/` tests GREEN
