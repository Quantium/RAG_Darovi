# Phase 3: File Download & Conversion to Text

**Goal**: Implement the Google Drive download pipeline and all file converters so that files are downloaded to MinIO and converted to plain text ready for indexing.

**Depends on**: Phase 2 (all tests written in RED state).

**Success Criteria**: Tests in `test_storage`, `test_metadata`, `test_drive`, `test_converter`, and `test_vectorizer/test_chunker.py` turn GREEN. A file can be downloaded from Drive, stored in MinIO, converted to text, chunked, and the text stored back in MinIO. The downloader supports initial full-scan bootstrap and detects deleted files during incremental sync.

---

## Step 3.1 — Storage Backend

**File**: `src/storage/backend.py`

**Contract** (Protocol):

```python
from __future__ import annotations
from typing import Protocol


class StorageBackend(Protocol):
    def upload(self, bucket: str, key: str, data: bytes) -> None: ...
    def download(self, bucket: str, key: str) -> bytes: ...
    def exists(self, bucket: str, key: str) -> bool: ...
    def delete(self, bucket: str, key: str) -> None: ...
    def ensure_buckets(self) -> None: ...
```

> **Note on sync vs async**: The `minio` Python client is synchronous. These methods are intentionally sync. When called from async contexts (FastAPI routes, async Celery wrappers), use `await asyncio.to_thread(storage.upload, ...)` to avoid blocking the event loop.

**Implementations**:

1. `MinIOStorage` — Primary implementation using `minio` Python client.
2. `LocalStorage` — Fallback using local filesystem (`pathlib.Path`).

**`MinIOStorage` constructor** (supports dependency injection for testing):

```python
from minio import Minio
from config.settings import Settings


class MinIOStorage:
    def __init__(self, settings: Settings, client: Minio | None = None) -> None:
        self._client = client or Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )
        self._bucket_raw = settings.minio_bucket_raw
        self._bucket_text = settings.minio_bucket_text
```

**`LocalStorage` constructor**:

```python
from pathlib import Path


class LocalStorage:
    def __init__(self, base_path: Path) -> None:
        self._base = base_path
```

**Key behavior**:
- `ensure_buckets()` creates `raw-files` and `converted-texts` if they don't exist.
- `upload()` wraps `data` in `BytesIO` and calls `put_object` with correct `length`.
- `download()` returns `bytes` (reads the response object and closes it).

**Tests to turn GREEN**: `tests/test_storage/test_backend.py`

**SC**: `pytest tests/test_storage/ -v` → all pass.

---

## Step 3.2 — Metadata Repository

**File**: `src/metadata/repository.py`

**Declarative base** (shared by all models in the project):

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass
```

**SQLAlchemy models**:

```python
class FileRecord(Base):
    __tablename__ = "file_records"

    drive_file_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    drive_modified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    minio_raw_key: Mapped[str | None] = mapped_column(String, nullable=True)
    minio_text_key: Mapped[str | None] = mapped_column(String, nullable=True)


class SyncState(Base):
    """Stores the Google Drive changes.list page token for incremental sync."""
    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String, primary_key=True, default="drive_page_token")
    value: Mapped[str] = mapped_column(String, nullable=False, default="")
```

**Repository class**: `MetadataRepository`

Constructor:

```python
from sqlalchemy.ext.asyncio import AsyncSession


class MetadataRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
```

Methods:
- `create_file_record(...)` — Insert with `pending` status.
- `get_file(drive_file_id)` — Fetch by PK. Returns `FileRecord | None`.
- `update_status(drive_file_id, status, error_message=None)` — Transition status.
- `list_by_status(status)` — Filter by status enum. Returns `list[FileRecord]`.
- `upsert_file(...)` — Insert or update on conflict (uses `insert(...).on_conflict_do_update()`).
- `update_chunk_count(drive_file_id, count)` — Set chunk count.
- `get_page_token()` — Returns the stored token from `SyncState`, or creates a default entry.
- `update_page_token(token)` — Persists new `startPageToken` in `SyncState`.

Use `AsyncSession` with `asyncpg` for production; tests use `aiosqlite`.

**Database table creation**:
- For **tests**: The `db_session` fixture in `conftest.py` calls `Base.metadata.create_all()`.
- For **production**: Add a startup function (called from the FastAPI `lifespan` or a CLI command) that creates tables if they don't exist:

```python
from sqlalchemy.ext.asyncio import create_async_engine

async def init_db(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
```

> **Note**: For a production system with schema evolution, consider adding Alembic migrations in a future iteration. For the initial implementation, `create_all()` is sufficient since no schema changes are expected.

**Tests to turn GREEN**: `tests/test_metadata/test_repository.py`

**SC**: `pytest tests/test_metadata/ -v` → all pass.

---

## Step 3.3 — Drive Auth

**File**: `src/drive/auth.py`

**Function**: `build_drive_service(credentials_path: str) -> Resource`

- Loads service account JSON via `google.oauth2.service_account.Credentials`.
- Scopes: `['https://www.googleapis.com/auth/drive.readonly']` — read-only for all Drive operations.
- Returns `googleapiclient.discovery.build("drive", "v3", credentials=creds)`.
- Raises `FileNotFoundError` if path missing, `ValueError` if JSON malformed.

> **Scope separation**: Google Sheets *writing* (via `gspread` in `SheetsWriter`, Phase 6) requires `https://www.googleapis.com/auth/spreadsheets` scope. This is handled by `SheetsWriter` using its own credentials path (`settings.google_sheets_credentials`), **not** the Drive service. The same service-account JSON file can be used for both, but each client requests only the scopes it needs. This avoids granting write access to the Drive download path.

**Tests to turn GREEN**: `tests/test_drive/test_auth.py`

**SC**: `pytest tests/test_drive/test_auth.py -v` → all pass.

---

## Step 3.4 — Drive Downloader

**File**: `src/drive/downloader.py`

**Class**: `DriveDownloader`

Constructor dependencies (injected):
- `drive_service` — Google Drive API resource
- `storage` — `StorageBackend`
- `metadata_repo` — `MetadataRepository`
- `settings` — `Settings`

**Methods**:

- `async full_sync() -> list[dict]`:
  1. Used for **initial bootstrap** when no `startPageToken` exists yet.
  2. Call `files.list(q="'{folder_id}' in parents", spaces="drive", fields=...)` with pagination (`nextPageToken`).
  3. Collect all file metadata dicts.
  4. Acquire a `startPageToken` via `changes.getStartPageToken()` and persist it for future incremental syncs.
  5. Return the full file list.

  > **Why**: `changes.list` only returns changes *after* a token is acquired. On first run, existing files would never be discovered without a full scan.

- `async incremental_sync() -> tuple[list[dict], list[str]]`:
  1. Read `startPageToken` from metadata DB.
  2. If no token exists, delegate to `full_sync()` and return `(files, [])`.
  3. Call `changes.list(pageToken=token, spaces="drive", fields=...)`.
  4. Separate results into **changed files** (have `file` key) and **deleted file IDs** (have `removed: true` or `file.trashed: true`).
  5. Persist new `startPageToken`.
  6. Return `(changed_files, deleted_file_ids)`.

- `async download_file(file_meta: dict) -> str | None`:
  1. Check if file's `modifiedTime` matches the stored `drive_modified_at` — if unchanged, return `None` (skip).
  2. Determine export type: Google Docs → `text/plain`, Sheets → `text/csv`, else binary download.
  3. Download bytes via `files.get_media()` or `files.export_media()`.
  4. Upload to MinIO `raw-files/{drive_file_id}/{name}` (use `asyncio.to_thread()` for the sync MinIO call).
  5. Create/update metadata record with `downloaded` status.
  6. Return the MinIO key.

**Error handling**:
- Retry on 429 (rate limit) with exponential backoff.
- Skip files whose `drive_modified_at` hasn't changed (return `None`).

**File deletion detection**: The `incremental_sync` method now returns deleted file IDs alongside changed files. The Celery orchestrator (Phase 4) is responsible for dispatching `delete_file_vectors` tasks for each deleted ID.

**Async/sync interop**: This class is `async` (its methods use `await`). When called from synchronous Celery tasks (Phase 4), the task must bridge using `asyncio.run()`:

```python
import asyncio

def download_file_task(file_meta: dict) -> dict:
    result = asyncio.run(downloader.download_file(file_meta))
    ...
```

> **Note**: This module is pure business logic — it has no dependency on Celery. The Celery wrapper lives in `src/worker/tasks.py` (Phase 4).

**Tests to turn GREEN**: `tests/test_drive/test_downloader.py`

**SC**: `pytest tests/test_drive/ -v` → all pass.

---

## Step 3.5 — FileConverter Protocol

**File**: `src/converter/base.py`

```python
from typing import Protocol

class FileConverter(Protocol):
    def convert(self, raw_bytes: bytes, file_name: str, mime_type: str) -> str:
        """Convert raw file bytes to plain text."""
        ...
```

All converters implement this protocol.

---

## Step 3.6 — PDF Converter

**File**: `src/converter/pdf_converter.py`

**Class**: `PdfConverter` (implements `FileConverter`)

**Logic**:
1. Try `pdfplumber.open()` on the bytes (wrap in `BytesIO`).
2. Extract text page by page. Detect tables with `page.extract_tables()` and format as markdown tables.
3. If a page has no text, fall back to OCR: `pdf2image.convert_from_bytes()` → `pytesseract.image_to_string()`.
4. Join pages with `\n\n--- PAGE {n} ---\n\n` markers.

**Tests to turn GREEN**: `tests/test_converter/test_pdf_converter.py`

**SC**: `pytest tests/test_converter/test_pdf_converter.py -v` → all pass.

---

## Step 3.7 — Docs Converter

**File**: `src/converter/docs_converter.py`

**Class**: `DocsConverter` (implements `FileConverter`)

**Logic**:
1. Input is already plain text (downloaded via Drive export as `text/plain`).
2. Normalize whitespace, preserve heading structure.
3. Return cleaned text.

**Tests to turn GREEN**: `tests/test_converter/test_docs_converter.py`

**SC**: `pytest tests/test_converter/test_docs_converter.py -v` → all pass.

---

## Step 3.8 — Sheets Converter

**File**: `src/converter/sheets_converter.py`

**Class**: `SheetsConverter` (implements `FileConverter`)

> **Important**: The Google Drive `export(mimeType='text/csv')` API only exports the **first sheet** of a spreadsheet. To support multi-sheet workbooks, the `DriveDownloader` (Step 3.4) exports Sheets as CSV for the first sheet, but also stores additional sheet data when available. For full multi-sheet support, the downloader uses the Sheets API (`spreadsheets.values.batchGet`) to fetch all sheets by name, concatenating them with `\n\n--- SHEET: {name} ---\n\n` separators before storing in MinIO.

**Logic**:
1. Input is text containing one or more sheets separated by `--- SHEET: {name} ---` markers (or plain CSV for single-sheet files).
2. Parse each sheet section as CSV, format with a `## Sheet: {name}` markdown header.
3. Preserve the header row for each sheet section.
4. Return formatted text.

**Tests to turn GREEN**: `tests/test_converter/test_sheets_converter.py`

**SC**: `pytest tests/test_converter/test_sheets_converter.py -v` → all pass.

---

## Step 3.8b — Additional File Converters

To handle common file types found in corporate Google Drive folders beyond PDFs and Google-native formats:

### `src/converter/docx_converter.py`

**Class**: `DocxConverter` (implements `FileConverter`)

**Logic**:
1. Open bytes as `.docx` via `python-docx` (`docx.Document(BytesIO(raw_bytes))`).
2. Extract paragraphs. Map styles: `Heading 1` → `# `, `Heading 2` → `## `, etc.
3. Extract tables as markdown tables.
4. Return combined text.

### `src/converter/xlsx_converter.py`

**Class**: `XlsxConverter` (implements `FileConverter`)

**Logic**:
1. Open bytes via `openpyxl` (`load_workbook(BytesIO(raw_bytes), read_only=True)`).
2. Iterate all sheets. Format each with `## Sheet: {name}` header.
3. Extract rows as CSV-like text, preserving header row.
4. Return combined text.

### `src/converter/text_converter.py`

**Class**: `TextConverter` (implements `FileConverter`)

Handles `text/plain`, `text/markdown`, and `text/html`:
1. For `text/plain` and `text/markdown`: decode UTF-8, return as-is (markdown structure preserved).
2. For `text/html`: parse with `BeautifulSoup(raw_bytes, "html.parser")`, extract text via `.get_text(separator="\n")`, strip tags.

### Tests

Add corresponding test files:
- `tests/test_converter/test_docx_converter.py`
- `tests/test_converter/test_xlsx_converter.py`
- `tests/test_converter/test_text_converter.py`

Each with basic extraction, empty input, and structure-preservation tests (same pattern as PDF/Docs/Sheets tests).

---

## Step 3.9 — Converter Factory

**File**: `src/converter/__init__.py`

A factory function that selects the correct converter based on MIME type, adhering to Open/Closed principle (new converters are added here without modifying existing ones):

```python
from __future__ import annotations

import structlog

from src.converter.base import FileConverter
from src.converter.pdf_converter import PdfConverter
from src.converter.docs_converter import DocsConverter
from src.converter.sheets_converter import SheetsConverter
from src.converter.docx_converter import DocxConverter
from src.converter.xlsx_converter import XlsxConverter
from src.converter.text_converter import TextConverter

logger = structlog.get_logger()

_CONVERTERS: dict[str, type[FileConverter]] = {
    "application/pdf": PdfConverter,
    "application/vnd.google-apps.document": DocsConverter,
    "application/vnd.google-apps.spreadsheet": SheetsConverter,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxConverter,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": XlsxConverter,
    "text/plain": TextConverter,
    "text/markdown": TextConverter,
    "text/html": TextConverter,
    "text/csv": SheetsConverter,
}


def get_converter(mime_type: str) -> FileConverter:
    """Return the appropriate converter for the given MIME type.

    Logs a warning and raises ValueError for unsupported types.
    """
    converter_cls = _CONVERTERS.get(mime_type)
    if converter_cls is None:
        logger.warning("converter.unsupported_mime_type", mime_type=mime_type)
        raise ValueError(f"No converter registered for MIME type: {mime_type}")
    return converter_cls()
```

This factory is used by the `convert_file` Celery task (Phase 4) instead of inline MIME-based if/elif chains. Unsupported MIME types are logged and skipped by the task (status set to `skipped` instead of `failed`).

---

## Step 3.10 — Structured Logging Setup

**File**: `src/logging.py` (new, single-responsibility module)

Initialize `structlog` once, imported by all modules:

```python
from __future__ import annotations

import structlog


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

Call `configure_logging()` in:
- The FastAPI `lifespan` (Phase 7)
- The Celery app setup (Phase 4)
- The CLI entry point (Phase 7)

All modules use `structlog.get_logger()` directly — no need to import this module after initial setup.

---

## Step 3.11 — Document-Aware Chunker

**File**: `src/vectorizer/chunker.py`

**Class**: `DocumentChunker`

**Chunk dataclass**:

```python
@dataclass
class Chunk:
    text: str
    source_file_id: str
    source_name: str
    document_type: str
    section_title: str
    chunk_index: int
    page_number: int | None = None
```

**Token counting**: Use `tiktoken` with the `cl100k_base` encoding (compatible with most embedding models). This gives accurate token counts vs. naive `split()` word counts, which undercount by ~30% for typical English text. The encoder is loaded once at `DocumentChunker.__init__` and reused:

```python
import tiktoken

class DocumentChunker:
    def __init__(self, max_tokens: int = 512, overlap: int = 50) -> None:
        self._max_tokens = max_tokens
        self._overlap = overlap
        self._enc = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(self, text: str) -> int:
        return len(self._enc.encode(text))
```

**Chunking strategies** (selected by document type):

| Document Type | Strategy |
|---|---|
| `doc` / `docx` | Split by headings (`#`, `##`), then by paragraphs. Max 512 tokens per chunk, 50-token overlap. |
| `sheet` / `xlsx` | Each row or row group becomes a chunk. Table headers prepended to every chunk. |
| `pdf` | Split by page markers (`--- PAGE N ---`), then by paragraphs. Tables kept intact. |
| `html` | Strip remaining tags, then heading-aware splitting like `doc`. |
| fallback | Token-based splitting: 512 tokens, 50-token overlap. |

Every chunk carries full metadata.

**Tests to turn GREEN**: `tests/test_vectorizer/test_chunker.py`

**SC**: `pytest tests/test_vectorizer/test_chunker.py -v` → all pass.

---

## Step 3.12 — Integration Verification

Run all tests for this phase together:

```bash
pytest tests/test_storage/ tests/test_metadata/ tests/test_drive/ tests/test_converter/ tests/test_vectorizer/test_chunker.py -v
```

All should be GREEN.

### Implementation order within this phase

Steps 3.1 and 3.2 have no data dependency and **can be implemented in parallel**. Steps 3.3–3.4 depend on 3.1 and 3.2. Steps 3.5–3.9 are independent from 3.3–3.4 and can also be parallelized. Step 3.11 depends on converters (3.5–3.8) being complete.

```
3.1 (Storage) ──┐
                 ├──→ 3.3 (Auth) → 3.4 (Downloader)
3.2 (Metadata) ──┘

3.5 (Protocol) → 3.6 (PDF) ───┐
                 3.7 (Docs) ───┤
                 3.8 (Sheets) ─┼──→ 3.9 (Factory)
                 3.8b (Docx) ──┤
                 3.8b (Xlsx) ──┤
                 3.8b (Text) ──┘

3.10 (Logging) — independent

3.11 (Chunker with tiktoken) — independent
```

---

## Output of This Phase

- `src/storage/backend.py` — `StorageBackend` protocol + `MinIOStorage` (with DI) + `LocalStorage`
- `src/metadata/repository.py` — `Base`, `FileRecord`, `SyncState` models + `MetadataRepository` + `init_db()`
- `src/drive/auth.py` — Drive service builder (read-only scope; Sheets write scope handled separately by `SheetsWriter`)
- `src/drive/downloader.py` — `full_sync()` for initial bootstrap + `incremental_sync()` returning `(changed_files, deleted_file_ids)` + `download_file()` (async, returns `str | None`)
- `src/converter/base.py` — `FileConverter` protocol
- `src/converter/pdf_converter.py` — PDF text extraction + OCR
- `src/converter/docs_converter.py` — Google Docs export
- `src/converter/sheets_converter.py` — Google Sheets export (multi-sheet via Sheets API)
- `src/converter/docx_converter.py` — Microsoft Word `.docx` extraction via `python-docx`
- `src/converter/xlsx_converter.py` — Microsoft Excel `.xlsx` extraction via `openpyxl`
- `src/converter/text_converter.py` — `text/plain`, `text/markdown`, `text/html` handling
- `src/converter/__init__.py` — Converter factory with expanded MIME type registry
- `src/logging.py` — `structlog` configuration
- `src/vectorizer/chunker.py` — Document-aware chunking with `tiktoken` token counting
- All corresponding tests in GREEN state
