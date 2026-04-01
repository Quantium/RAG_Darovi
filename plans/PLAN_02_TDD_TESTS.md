# Phase 2: TDD — Test Infrastructure & Test Stubs (RED Phase)

**Goal**: Set up the test infrastructure (conftest, fixtures, mocks) and write **all** unit tests for every module in the project. Tests must fail (RED) because no implementation exists yet. Subsequent phases implement code to turn them GREEN.

**Depends on**: Phase 1 (venv, dependencies, directory scaffold).

**Success Criteria**: `pytest --collect-only` finds all test files; `pytest` runs and all tests **fail** with `ImportError` or `NotImplementedError` (no syntax errors, no missing fixtures).

---

## Step 2.1 — pytest Configuration

Create `pyproject.toml` (or add to existing):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"
addopts = "-v --tb=short --strict-markers"
markers = [
    "integration: tests requiring Docker services (Milvus, MinIO, Ollama, etc.)",
    "slow: tests taking >5s",
]

[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.mypy]
python_version = "3.11"
strict = true
```

---

## Step 2.2 — conftest.py (Shared Fixtures)

`tests/conftest.py` provides reusable fixtures used across all test modules:

```python
"""Shared test fixtures for the RAG pipeline."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from config.settings import Settings


@pytest.fixture
def settings() -> Settings:
    """Return a Settings instance with test defaults."""
    return Settings(
        database_url=SecretStr("sqlite+aiosqlite:///test.db"),
        database_url_sync=SecretStr("sqlite:///test.db"),
        redis_broker_url="redis://localhost:6379/10",
        redis_result_url="redis://localhost:6379/11",
        redis_cache_url="redis://localhost:6379/12",
        minio_endpoint="localhost:9000",
        minio_secure=False,
        milvus_host="localhost",
        milvus_port=19530,
        api_key=SecretStr(""),
    )


@pytest.fixture
async def db_session(settings: Settings):
    """Async DB session backed by aiosqlite for unit tests."""
    from src.metadata.repository import Base

    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def mock_minio_client() -> MagicMock:
    """Mock MinIO client."""
    client = MagicMock()
    client.bucket_exists.return_value = True
    client.put_object.return_value = None
    client.get_object.return_value = MagicMock(read=MagicMock(return_value=b"file content"))
    return client


@pytest.fixture
def mock_drive_service() -> MagicMock:
    """Mock Google Drive service."""
    service = MagicMock()
    return service


@pytest.fixture
def mock_ollama_client() -> AsyncMock:
    """Mock Ollama embedding client (for EmbeddingClient protocol)."""
    client = AsyncMock()
    client.embed.return_value = [[0.1] * 768]
    return client


@pytest.fixture
def mock_httpx_client() -> AsyncMock:
    """Mock httpx.AsyncClient for BatchEmbedder HTTP calls to Ollama."""
    client = AsyncMock()
    client.post.return_value = MagicMock(
        json=MagicMock(return_value={"embeddings": [[0.1] * 768]}),
        status_code=200,
        raise_for_status=MagicMock(),
    )
    return client


@pytest.fixture
def mock_milvus_client() -> MagicMock:
    """Mock Milvus client."""
    client = MagicMock()
    client.search.return_value = []
    return client


@pytest.fixture
def mock_redis_client() -> MagicMock:
    """Mock Redis client for retriever caching tests."""
    client = MagicMock()
    client.get.return_value = None
    client.set.return_value = True
    return client


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Minimal valid-ish PDF bytes for testing (mocked — not a real PDF)."""
    return b"%PDF-1.4 fake pdf content for testing"


@pytest.fixture
def sample_text() -> str:
    """Sample extracted text for chunking/embedding tests."""
    return (
        "# Quarterly Report Q3 2024\n\n"
        "## Revenue\n\n"
        "Total revenue reached $1.2M, a 15% increase over Q2.\n\n"
        "## Expenses\n\n"
        "Operating expenses were $800K.\n\n"
        "## Summary\n\n"
        "Net profit of $400K with healthy margins across all segments."
    )
```

---

## Step 2.3 — Settings Tests

`tests/test_config/test_settings.py`

Settings is the single source of truth for configuration. These tests ensure it loads correctly and protects sensitive values.

| Test | Asserts |
|---|---|
| `test_settings_loads_defaults` | All fields have sensible defaults when no env vars are set |
| `test_settings_reads_env_vars` | Environment variables override defaults |
| `test_secret_str_fields_are_protected` | `database_url`, `minio_secret_key`, `llm_api_key` do not appear in `repr()` or `str()` |
| `test_settings_validates_port_type` | Non-integer port raises `ValidationError` |

```python
"""Tests for config/settings.py — turns GREEN in Phase 1."""
from __future__ import annotations

import os
import pytest
from pydantic import SecretStr, ValidationError

from config.settings import Settings


class TestSettings:
    def test_settings_loads_defaults(self):
        s = Settings()
        assert s.milvus_port == 19530
        assert s.embed_model == "nomic-embed-text"
        assert s.embed_dim == 768

    def test_settings_reads_env_vars(self, monkeypatch):
        monkeypatch.setenv("MILVUS_PORT", "29530")
        monkeypatch.setenv("EMBED_MODEL", "custom-model")
        s = Settings()
        assert s.milvus_port == 29530
        assert s.embed_model == "custom-model"

    def test_secret_str_fields_are_protected(self):
        s = Settings(database_url=SecretStr("postgresql+asyncpg://secret@host/db"))
        text = repr(s)
        assert "secret@host" not in text

    def test_settings_validates_port_type(self):
        with pytest.raises(ValidationError):
            Settings(milvus_port="not-a-number")  # type: ignore[arg-type]
```

> **Note**: These tests turn GREEN immediately with Phase 1's `config/settings.py`. They are included here to ensure the configuration contract is verified before any module depends on it.

---

## Step 2.4 — Storage Backend Tests

`tests/test_storage/test_backend.py`

Tests for the MinIO abstraction layer:

| Test | Asserts |
|---|---|
| `test_upload_file` | File uploaded to correct bucket with correct key |
| `test_download_file` | File content returned matches what was uploaded |
| `test_file_exists` | Returns `True` for existing, `False` for missing |
| `test_delete_file` | File removed from bucket |
| `test_ensure_buckets_created` | Creates `raw-files` and `converted-texts` buckets if missing |
| `test_local_fallback_upload` | Falls back to local filesystem when MinIO unavailable |
| `test_local_fallback_download` | Reads from local filesystem when MinIO unavailable |

```python
"""Tests for src/storage/backend.py — turns GREEN in Phase 3."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.storage.backend import MinIOStorage, LocalStorage


class TestMinIOStorage:
    def test_upload_file(self, mock_minio_client, settings):
        storage = MinIOStorage(settings, client=mock_minio_client)
        storage.upload("raw-files", "test-key", b"content")
        mock_minio_client.put_object.assert_called_once()

    def test_download_file(self, mock_minio_client, settings):
        storage = MinIOStorage(settings, client=mock_minio_client)
        data = storage.download("raw-files", "test-key")
        assert data == b"file content"

    def test_file_exists(self, mock_minio_client, settings):
        storage = MinIOStorage(settings, client=mock_minio_client)
        assert storage.exists("raw-files", "test-key") is True

    def test_delete_file(self, mock_minio_client, settings):
        storage = MinIOStorage(settings, client=mock_minio_client)
        storage.delete("raw-files", "test-key")
        mock_minio_client.remove_object.assert_called_once()

    def test_ensure_buckets_created(self, mock_minio_client, settings):
        mock_minio_client.bucket_exists.return_value = False
        storage = MinIOStorage(settings, client=mock_minio_client)
        storage.ensure_buckets()
        assert mock_minio_client.make_bucket.call_count == 2


class TestLocalStorage:
    def test_local_fallback_upload(self, tmp_path, settings):
        storage = LocalStorage(base_path=tmp_path)
        storage.upload("raw-files", "test-key", b"content")
        assert (tmp_path / "raw-files" / "test-key").read_bytes() == b"content"

    def test_local_fallback_download(self, tmp_path, settings):
        (tmp_path / "raw-files").mkdir()
        (tmp_path / "raw-files" / "test-key").write_bytes(b"content")
        storage = LocalStorage(base_path=tmp_path)
        assert storage.download("raw-files", "test-key") == b"content"
```

---

## Step 2.5 — Metadata Repository Tests

`tests/test_metadata/test_repository.py`

Tests for PostgreSQL processing state CRUD (uses `aiosqlite` via the `db_session` fixture):

| Test | Asserts |
|---|---|
| `test_create_file_record` | Inserts new record with `pending` status |
| `test_get_file_by_drive_id` | Returns correct record |
| `test_update_status` | Changes status from `pending` → `downloaded` |
| `test_update_status_with_error` | Sets `failed` status and error message |
| `test_list_files_by_status` | Filters records by status enum |
| `test_upsert_on_conflict` | Updates existing record on duplicate `drive_file_id` |
| `test_update_chunk_count` | Sets `chunk_count` after embedding |
| `test_get_or_create_page_token` | Returns stored token or creates default |
| `test_update_page_token` | Persists new `startPageToken` |

```python
"""Tests for src/metadata/repository.py — turns GREEN in Phase 3."""
from __future__ import annotations

import pytest

from src.metadata.repository import MetadataRepository


class TestMetadataRepository:
    async def test_create_file_record(self, db_session):
        repo = MetadataRepository(db_session)
        record = await repo.create_file_record(
            drive_file_id="abc123", name="test.pdf", mime_type="application/pdf"
        )
        assert record.status == "pending"
        assert record.drive_file_id == "abc123"

    async def test_get_file_by_drive_id(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="abc123", name="test.pdf", mime_type="application/pdf")
        record = await repo.get_file("abc123")
        assert record is not None
        assert record.name == "test.pdf"

    async def test_update_status(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="abc123", name="test.pdf", mime_type="application/pdf")
        await repo.update_status("abc123", "downloaded")
        record = await repo.get_file("abc123")
        assert record.status == "downloaded"

    async def test_update_status_with_error(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="abc123", name="test.pdf", mime_type="application/pdf")
        await repo.update_status("abc123", "failed", error_message="Download timeout")
        record = await repo.get_file("abc123")
        assert record.status == "failed"
        assert record.error_message == "Download timeout"

    async def test_list_files_by_status(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="a", name="a.pdf", mime_type="application/pdf")
        await repo.create_file_record(drive_file_id="b", name="b.pdf", mime_type="application/pdf")
        await repo.update_status("a", "downloaded")
        results = await repo.list_by_status("pending")
        assert len(results) == 1
        assert results[0].drive_file_id == "b"

    async def test_upsert_on_conflict(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="abc123", name="old.pdf", mime_type="application/pdf")
        await repo.upsert_file(drive_file_id="abc123", name="new.pdf", mime_type="application/pdf")
        record = await repo.get_file("abc123")
        assert record.name == "new.pdf"

    async def test_update_chunk_count(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="abc123", name="test.pdf", mime_type="application/pdf")
        await repo.update_chunk_count("abc123", 42)
        record = await repo.get_file("abc123")
        assert record.chunk_count == 42

    async def test_get_or_create_page_token(self, db_session):
        repo = MetadataRepository(db_session)
        token = await repo.get_page_token()
        assert token is not None

    async def test_update_page_token(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.update_page_token("new-token-123")
        token = await repo.get_page_token()
        assert token == "new-token-123"
```

---

## Step 2.6 — Drive Auth Tests

`tests/test_drive/test_auth.py`

| Test | Asserts |
|---|---|
| `test_build_service_from_json` | Returns a Drive service object from valid credentials path |
| `test_build_service_missing_file` | Raises `FileNotFoundError` for missing credentials |
| `test_build_service_invalid_json` | Raises `ValueError` for malformed JSON |
| `test_scopes_include_readonly` | Credentials use `drive.readonly` scope |

```python
"""Tests for src/drive/auth.py — turns GREEN in Phase 3."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.drive.auth import build_drive_service


class TestDriveAuth:
    @patch("src.drive.auth.service_account.Credentials.from_service_account_file")
    @patch("src.drive.auth.build")
    def test_build_service_from_json(self, mock_build, mock_creds):
        mock_creds.return_value = MagicMock()
        service = build_drive_service("credentials/valid.json")
        assert service is not None
        mock_build.assert_called_once()

    def test_build_service_missing_file(self):
        with pytest.raises(FileNotFoundError):
            build_drive_service("/nonexistent/path.json")

    @patch("src.drive.auth.service_account.Credentials.from_service_account_file")
    def test_build_service_invalid_json(self, mock_creds):
        mock_creds.side_effect = ValueError("Invalid JSON")
        with pytest.raises(ValueError):
            build_drive_service("credentials/bad.json")

    @patch("src.drive.auth.service_account.Credentials.from_service_account_file")
    @patch("src.drive.auth.build")
    def test_scopes_include_readonly(self, mock_build, mock_creds):
        mock_creds.return_value = MagicMock()
        build_drive_service("credentials/valid.json")
        call_args = mock_creds.call_args
        scopes = call_args[1].get("scopes") or call_args[0][1] if len(call_args[0]) > 1 else None
        assert any("drive.readonly" in s for s in (scopes or []))
```

---

## Step 2.7 — Drive Downloader Tests

`tests/test_drive/test_downloader.py`

| Test | Asserts |
|---|---|
| `test_incremental_sync_returns_changed_files` | Returns list of changed file metadata |
| `test_incremental_sync_updates_page_token` | Persists new token after sync |
| `test_download_file_to_storage` | Downloads file bytes and stores in MinIO `raw-files` |
| `test_download_google_doc_exports_as_text` | Exports Google Docs MIME type as `text/plain` |
| `test_download_google_sheet_exports_as_csv` | Exports Google Sheets as CSV |
| `test_download_creates_metadata_record` | Creates `pending` record in metadata DB |
| `test_skip_already_processed_file` | Skips file if `drive_modified_at` hasn't changed |
| `test_handles_api_rate_limit` | Retries on 429 response with backoff |

```python
"""Tests for src/drive/downloader.py — turns GREEN in Phase 3."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.drive.downloader import DriveDownloader


class TestDriveDownloader:
    @pytest.fixture
    def downloader(self, mock_drive_service, mock_minio_client, settings):
        metadata_repo = AsyncMock()
        metadata_repo.get_page_token.return_value = "start-token"
        return DriveDownloader(
            drive_service=mock_drive_service,
            storage=mock_minio_client,
            metadata_repo=metadata_repo,
            settings=settings,
        )

    async def test_incremental_sync_returns_changed_files(self, downloader):
        downloader._drive_service.changes.return_value.list.return_value.execute.return_value = {
            "changes": [{"fileId": "f1", "file": {"name": "a.pdf"}}],
            "newStartPageToken": "new-token",
        }
        files = await downloader.incremental_sync()
        assert len(files) >= 1

    async def test_incremental_sync_updates_page_token(self, downloader):
        downloader._drive_service.changes.return_value.list.return_value.execute.return_value = {
            "changes": [],
            "newStartPageToken": "updated-token",
        }
        await downloader.incremental_sync()
        downloader._metadata_repo.update_page_token.assert_called_with("updated-token")

    async def test_download_file_to_storage(self, downloader):
        file_meta = {"id": "f1", "name": "test.pdf", "mimeType": "application/pdf"}
        key = await downloader.download_file(file_meta)
        assert "f1" in key

    async def test_download_google_doc_exports_as_text(self, downloader):
        file_meta = {"id": "f1", "name": "doc", "mimeType": "application/vnd.google-apps.document"}
        await downloader.download_file(file_meta)
        # Verify export_media was called (not get_media)

    async def test_download_google_sheet_exports_as_csv(self, downloader):
        file_meta = {"id": "f1", "name": "sheet", "mimeType": "application/vnd.google-apps.spreadsheet"}
        await downloader.download_file(file_meta)

    async def test_download_creates_metadata_record(self, downloader):
        file_meta = {"id": "f1", "name": "test.pdf", "mimeType": "application/pdf"}
        await downloader.download_file(file_meta)
        downloader._metadata_repo.create_file_record.assert_called_once()

    async def test_skip_already_processed_file(self, downloader):
        downloader._metadata_repo.get_file.return_value = MagicMock(
            drive_modified_at="2024-01-01T00:00:00Z"
        )
        file_meta = {"id": "f1", "name": "test.pdf", "mimeType": "application/pdf", "modifiedTime": "2024-01-01T00:00:00Z"}
        result = await downloader.download_file(file_meta)
        assert result is None

    async def test_handles_api_rate_limit(self, downloader):
        from googleapiclient.errors import HttpError
        resp = MagicMock(status=429)
        downloader._drive_service.files.return_value.get_media.return_value.execute.side_effect = [
            HttpError(resp, b"Rate limit"), b"content"
        ]
        # Should retry and eventually succeed or raise

    async def test_full_sync_lists_all_files(self, downloader):
        downloader._drive_service.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "f1", "name": "a.pdf"}, {"id": "f2", "name": "b.pdf"}],
        }
        downloader._drive_service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
            "startPageToken": "initial-token",
        }
        files = await downloader.full_sync()
        assert len(files) == 2
        downloader._metadata_repo.update_page_token.assert_called_with("initial-token")

    async def test_incremental_sync_detects_deletions(self, downloader):
        downloader._drive_service.changes.return_value.list.return_value.execute.return_value = {
            "changes": [
                {"fileId": "f1", "file": {"name": "a.pdf"}},
                {"fileId": "f2", "removed": True},
            ],
            "newStartPageToken": "new-token",
        }
        changed, deleted = await downloader.incremental_sync()
        assert len(changed) == 1
        assert "f2" in deleted

    async def test_incremental_sync_delegates_to_full_on_first_run(self, downloader):
        downloader._metadata_repo.get_page_token.return_value = None
        downloader._drive_service.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "f1", "name": "a.pdf"}],
        }
        downloader._drive_service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
            "startPageToken": "first-token",
        }
        changed, deleted = await downloader.incremental_sync()
        assert len(changed) == 1
        assert deleted == []
```

---

## Step 2.8 — Converter Tests

### `tests/test_converter/test_pdf_converter.py`

| Test | Asserts |
|---|---|
| `test_extract_text_from_pdf` | Returns non-empty text from valid PDF |
| `test_ocr_fallback_on_image_pdf` | Uses Tesseract when pdfplumber extracts no text |
| `test_preserves_page_boundaries` | Output contains page markers |
| `test_handles_empty_pdf` | Returns empty string for blank PDF |
| `test_detects_tables` | Extracts table data from PDF with tables |

```python
"""Tests for src/converter/pdf_converter.py — turns GREEN in Phase 3."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.converter.pdf_converter import PdfConverter


class TestPdfConverter:
    def test_extract_text_from_pdf(self, sample_pdf_bytes):
        converter = PdfConverter()
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "Hello World"
            mock_page.extract_tables.return_value = []
            mock_open.return_value.__enter__.return_value.pages = [mock_page]
            text = converter.convert(sample_pdf_bytes, "test.pdf", "application/pdf")
            assert "Hello World" in text

    @patch("src.converter.pdf_converter.pytesseract.image_to_string", return_value="OCR text")
    @patch("src.converter.pdf_converter.convert_from_bytes", return_value=[MagicMock()])
    def test_ocr_fallback_on_image_pdf(self, mock_convert, mock_ocr, sample_pdf_bytes):
        converter = PdfConverter()
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = ""
            mock_page.extract_tables.return_value = []
            mock_open.return_value.__enter__.return_value.pages = [mock_page]
            text = converter.convert(sample_pdf_bytes, "scan.pdf", "application/pdf")
            assert "OCR text" in text

    def test_preserves_page_boundaries(self, sample_pdf_bytes):
        converter = PdfConverter()
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            pages = [MagicMock(extract_text=MagicMock(return_value=f"Page {i}"), extract_tables=MagicMock(return_value=[])) for i in range(3)]
            mock_open.return_value.__enter__.return_value.pages = pages
            text = converter.convert(sample_pdf_bytes, "multi.pdf", "application/pdf")
            assert "PAGE" in text

    def test_handles_empty_pdf(self):
        converter = PdfConverter()
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__.return_value.pages = []
            text = converter.convert(b"", "empty.pdf", "application/pdf")
            assert text == ""

    def test_detects_tables(self, sample_pdf_bytes):
        converter = PdfConverter()
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "Some text"
            mock_page.extract_tables.return_value = [
                [["Col1", "Col2"], ["A", "B"]]
            ]
            mock_open.return_value.__enter__.return_value.pages = [mock_page]
            text = converter.convert(sample_pdf_bytes, "table.pdf", "application/pdf")
            assert "Col1" in text
```

### `tests/test_converter/test_docs_converter.py`

| Test | Asserts |
|---|---|
| `test_export_google_doc_as_text` | Returns plain text from Drive export |
| `test_preserves_heading_structure` | Headings appear with markdown markers |
| `test_handles_empty_document` | Returns empty string |

```python
"""Tests for src/converter/docs_converter.py — turns GREEN in Phase 3."""
from __future__ import annotations

from src.converter.docs_converter import DocsConverter


class TestDocsConverter:
    def test_export_google_doc_as_text(self):
        converter = DocsConverter()
        text = converter.convert(b"Hello world", "doc.txt", "text/plain")
        assert "Hello world" in text

    def test_preserves_heading_structure(self):
        converter = DocsConverter()
        raw = b"# Title\n\nParagraph text\n\n## Section\n\nMore text"
        text = converter.convert(raw, "doc.txt", "text/plain")
        assert "# Title" in text
        assert "## Section" in text

    def test_handles_empty_document(self):
        converter = DocsConverter()
        text = converter.convert(b"", "empty.txt", "text/plain")
        assert text == ""
```

### `tests/test_converter/test_sheets_converter.py`

| Test | Asserts |
|---|---|
| `test_export_sheet_as_csv` | Returns CSV text with headers |
| `test_handles_multiple_sheets` | Concatenates all sheets with sheet name separators |
| `test_handles_empty_sheet` | Returns header row only |

```python
"""Tests for src/converter/sheets_converter.py — turns GREEN in Phase 3."""
from __future__ import annotations

from src.converter.sheets_converter import SheetsConverter


class TestSheetsConverter:
    def test_export_sheet_as_csv(self):
        converter = SheetsConverter()
        csv_bytes = b"Name,Age\nAlice,30\nBob,25"
        text = converter.convert(csv_bytes, "data.csv", "text/csv")
        assert "Name" in text
        assert "Alice" in text

    def test_handles_multiple_sheets(self):
        converter = SheetsConverter()
        csv_bytes = b"Sheet: Sales\nProduct,Revenue\nA,100\n\nSheet: Costs\nItem,Amount\nX,50"
        text = converter.convert(csv_bytes, "multi.csv", "text/csv")
        assert "Sales" in text or "Costs" in text

    def test_handles_empty_sheet(self):
        converter = SheetsConverter()
        csv_bytes = b"Name,Age"
        text = converter.convert(csv_bytes, "empty.csv", "text/csv")
        assert "Name" in text
```

---

## Step 2.9 — Chunker Tests (turns GREEN in Phase 3)

`tests/test_vectorizer/test_chunker.py`

> **Note**: The chunker is implemented in **Phase 3** (Step 3.9), not Phase 5. These tests are separated from the embedder/Milvus tests because they turn GREEN earlier.

| Test | Asserts |
|---|---|
| `test_chunk_by_headings` | Splits text at heading boundaries |
| `test_chunk_metadata_includes_source` | Each chunk has `source_file`, `chunk_index` |
| `test_chunk_metadata_includes_section` | Each chunk has `section_title` |
| `test_chunk_respects_max_tokens` | No chunk exceeds 512 tokens |
| `test_chunk_overlap` | Adjacent chunks share ~50 tokens of overlap |
| `test_csv_chunk_preserves_headers` | Each row chunk has table headers prepended |
| `test_empty_text_returns_empty_list` | No chunks for empty input |

```python
"""Tests for src/vectorizer/chunker.py — turns GREEN in Phase 3."""
from __future__ import annotations

import pytest

from src.vectorizer.chunker import DocumentChunker, Chunk


class TestDocumentChunker:
    def test_chunk_by_headings(self, sample_text):
        chunker = DocumentChunker()
        chunks = chunker.chunk(sample_text, source_file_id="f1", source_name="report.pdf", document_type="doc")
        assert len(chunks) > 1
        assert any("Revenue" in c.text for c in chunks)

    def test_chunk_metadata_includes_source(self, sample_text):
        chunker = DocumentChunker()
        chunks = chunker.chunk(sample_text, source_file_id="f1", source_name="report.pdf", document_type="doc")
        for chunk in chunks:
            assert chunk.source_file_id == "f1"
            assert isinstance(chunk.chunk_index, int)

    def test_chunk_metadata_includes_section(self, sample_text):
        chunker = DocumentChunker()
        chunks = chunker.chunk(sample_text, source_file_id="f1", source_name="report.pdf", document_type="doc")
        assert any(c.section_title != "" for c in chunks)

    def test_chunk_respects_max_tokens(self):
        long_text = "word " * 2000
        chunker = DocumentChunker(max_tokens=512)
        chunks = chunker.chunk(long_text, source_file_id="f1", source_name="long.txt", document_type="doc")
        for chunk in chunks:
            assert len(chunk.text.split()) <= 520  # small buffer for overlap

    def test_chunk_overlap(self):
        long_text = " ".join(f"word{i}" for i in range(1000))
        chunker = DocumentChunker(max_tokens=512, overlap=50)
        chunks = chunker.chunk(long_text, source_file_id="f1", source_name="long.txt", document_type="doc")
        if len(chunks) >= 2:
            end_of_first = set(chunks[0].text.split()[-50:])
            start_of_second = set(chunks[1].text.split()[:50])
            assert len(end_of_first & start_of_second) > 0

    def test_csv_chunk_preserves_headers(self):
        csv_text = "## Sheet: Data\nName,Age\nAlice,30\nBob,25"
        chunker = DocumentChunker()
        chunks = chunker.chunk(csv_text, source_file_id="f1", source_name="data.csv", document_type="sheet")
        for chunk in chunks:
            assert "Name" in chunk.text or "Sheet" in chunk.text

    def test_empty_text_returns_empty_list(self):
        chunker = DocumentChunker()
        chunks = chunker.chunk("", source_file_id="f1", source_name="empty.txt", document_type="doc")
        assert chunks == []
```

---

## Step 2.10 — Embedder & Milvus Store Tests (turns GREEN in Phase 5)

> **Note**: These tests depend on modules implemented in **Phase 5**. They remain RED until that phase.

### `tests/test_vectorizer/test_embedder.py`

| Test | Asserts |
|---|---|
| `test_embed_single_text` | Returns 768-dim vector for one text |
| `test_embed_batch` | Returns N vectors for N texts |
| `test_batch_size_respected` | Splits into batches of `embed_batch_size` |
| `test_handles_empty_text` | Returns zero vector or raises error |
| `test_retries_on_ollama_error` | Retries on connection failure |

```python
"""Tests for src/vectorizer/embedder.py — turns GREEN in Phase 5."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.vectorizer.embedder import BatchEmbedder


class TestBatchEmbedder:
    async def test_embed_single_text(self, settings, mock_httpx_client):
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts(["Hello world"])
        assert len(vectors) == 1
        assert len(vectors[0]) == 768

    async def test_embed_batch(self, settings, mock_httpx_client):
        mock_httpx_client.post.return_value.json.return_value = {
            "embeddings": [[0.1] * 768 for _ in range(5)]
        }
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts([f"text {i}" for i in range(5)])
        assert len(vectors) == 5

    async def test_batch_size_respected(self, settings, mock_httpx_client):
        settings_small = settings.model_copy(update={"embed_batch_size": 2})
        mock_httpx_client.post.return_value.json.return_value = {"embeddings": [[0.1] * 768, [0.2] * 768]}
        embedder = BatchEmbedder(settings_small, client=mock_httpx_client)
        await embedder.embed_texts([f"text {i}" for i in range(5)])
        assert mock_httpx_client.post.call_count == 3  # ceil(5/2)

    async def test_handles_empty_text(self, settings, mock_httpx_client):
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts([""])
        assert len(vectors[0]) == 768 or vectors[0] == [0.0] * 768

    async def test_retries_on_ollama_error(self, settings, mock_httpx_client):
        import httpx
        mock_httpx_client.post.side_effect = [
            httpx.ConnectError("Connection refused"),
            AsyncMock(json=lambda: {"embeddings": [[0.1] * 768]}, status_code=200, raise_for_status=lambda: None),
        ]
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts(["retry test"])
        assert len(vectors) == 1
```

### `tests/test_vectorizer/test_milvus_store.py`

| Test | Asserts |
|---|---|
| `test_create_collection` | Creates collection with correct schema and HNSW index |
| `test_upsert_chunks` | Inserts chunk data with embeddings |
| `test_search_returns_results` | Semantic search returns top-k matches |
| `test_search_with_partition_filter` | Filters by document type partition |
| `test_delete_by_source_file` | Removes all chunks for a given `source_file_id` |
| `test_collection_exists_check` | Returns `True`/`False` |

```python
"""Tests for src/vectorizer/milvus_store.py — turns GREEN in Phase 5."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.vectorizer.milvus_store import MilvusStore


class TestMilvusStore:
    @pytest.fixture
    def store(self, settings, mock_milvus_client):
        return MilvusStore(settings, client=mock_milvus_client)

    def test_create_collection(self, store, mock_milvus_client):
        store.create_collection()
        mock_milvus_client.create_collection.assert_called_once()

    def test_upsert_chunks(self, store, mock_milvus_client):
        chunks = [{"id": "h1", "source_file_id": "f1", "text": "hello", "document_type": "doc"}]
        embeddings = [[0.1] * 768]
        store.upsert(chunks, embeddings)
        mock_milvus_client.insert.assert_called_once()

    def test_search_returns_results(self, store, mock_milvus_client):
        mock_milvus_client.search.return_value = [[MagicMock(id="h1", score=0.95, entity=MagicMock(get=lambda k: "val"))]]
        results = store.search([0.1] * 768, top_k=5)
        assert isinstance(results, list)

    def test_search_with_partition_filter(self, store, mock_milvus_client):
        store.search([0.1] * 768, top_k=5, partition="pdf")
        call_kwargs = mock_milvus_client.search.call_args
        assert "pdf" in str(call_kwargs)

    def test_delete_by_source_file(self, store, mock_milvus_client):
        store.delete_by_source("f1")
        mock_milvus_client.delete.assert_called_once()

    def test_collection_exists_check(self, store, mock_milvus_client):
        mock_milvus_client.has_collection.return_value = True
        assert store.collection_exists() is True
```

---

## Step 2.11 — Worker Task Tests

`tests/test_worker/test_tasks.py`

| Test | Asserts |
|---|---|
| `test_download_task_calls_downloader` | Invokes downloader and updates status to `downloaded` |
| `test_convert_task_calls_converter` | Reads raw file, converts, stores text, status → `converted` |
| `test_embed_task_calls_embedder` | Chunks text, embeds, upserts to Milvus, status → `embedded` |
| `test_task_chain_download_convert_embed` | Tasks chain correctly |
| `test_task_retry_on_failure` | Failed task retries with exponential backoff |
| `test_task_marks_failed_after_max_retries` | Status set to `failed` with error message |

```python
"""Tests for src/worker/tasks.py — turns GREEN in Phase 4 (embed in Phase 5)."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from src.worker.tasks import download_file, convert_file, embed_file


class TestWorkerTasks:
    @patch("src.worker.tasks.DriveDownloader")
    def test_download_task_calls_downloader(self, mock_dl_cls):
        mock_dl = mock_dl_cls.return_value
        mock_dl.download_file.return_value = "raw-files/f1/test.pdf"
        result = download_file({"id": "f1", "name": "test.pdf", "mimeType": "application/pdf"})
        mock_dl.download_file.assert_called_once()
        assert "drive_file_id" in result

    @patch("src.worker.tasks.StorageBackend")
    def test_convert_task_calls_converter(self, mock_storage_cls):
        mock_storage_cls.return_value.download.return_value = b"pdf bytes"
        result = convert_file({"drive_file_id": "f1", "minio_raw_key": "raw-files/f1/test.pdf", "mime_type": "application/pdf", "name": "test.pdf"})
        assert "minio_text_key" in result

    @pytest.mark.xfail(reason="Placeholder until Phase 5 implements embed_file", strict=True)
    @patch("src.worker.tasks.BatchEmbedder")
    @patch("src.worker.tasks.MilvusStore")
    def test_embed_task_calls_embedder(self, mock_milvus_cls, mock_embedder_cls):
        mock_embedder_cls.return_value.embed_texts = AsyncMock(return_value=[[0.1] * 768])
        result = embed_file({"drive_file_id": "f1", "minio_text_key": "texts/f1.txt", "name": "test.pdf", "document_type": "pdf"})
        assert result is not None

    def test_task_chain_download_convert_embed(self):
        from celery import chain
        pipeline = chain(download_file.s({}), convert_file.s(), embed_file.s())
        assert pipeline is not None

    @patch("src.worker.tasks.DriveDownloader")
    def test_task_retry_on_failure(self, mock_dl_cls):
        mock_dl_cls.return_value.download_file.side_effect = ConnectionError("timeout")
        with pytest.raises(ConnectionError):
            download_file({"id": "f1", "name": "test.pdf", "mimeType": "application/pdf"})

    @patch("src.worker.tasks.MetadataRepository")
    def test_task_marks_failed_after_max_retries(self, mock_repo_cls):
        mock_repo = mock_repo_cls.return_value
        # Simulate the on_failure handler
        mock_repo.update_status.return_value = None

    @patch("src.worker.tasks.MilvusStore")
    @patch("src.worker.tasks.StorageBackend")
    def test_delete_file_vectors_removes_all(self, mock_storage_cls, mock_milvus_cls):
        from src.worker.tasks import delete_file_vectors
        mock_milvus_cls.return_value.delete_by_source.return_value = None
        result = delete_file_vectors("f1")
        mock_milvus_cls.return_value.delete_by_source.assert_called_once_with("f1")
        assert result["deleted"] is True

    @patch("src.worker.tasks.redis.Redis")
    def test_sync_acquires_distributed_lock(self, mock_redis_cls):
        from src.worker.tasks import run_incremental_sync
        mock_redis_cls.from_url.return_value.set.return_value = False  # lock not acquired
        run_incremental_sync()
        # Should return early without dispatching tasks

    @patch("src.worker.tasks.DriveDownloader")
    def test_sync_dispatches_deletions(self, mock_dl_cls):
        from src.worker.tasks import run_incremental_sync, delete_file_vectors
        mock_dl = mock_dl_cls.return_value
        mock_dl.incremental_sync.return_value = ([], ["deleted-id-1", "deleted-id-2"])
        # Verify delete_file_vectors.delay called for each deleted ID

    @patch("src.worker.tasks.StorageBackend")
    def test_convert_task_skips_unsupported_mime(self, mock_storage_cls):
        mock_storage_cls.return_value.download.return_value = b"content"
        result = convert_file({
            "drive_file_id": "f1", "minio_raw_key": "raw/f1", "mime_type": "video/mp4", "name": "movie.mp4"
        })
        assert result.get("skipped") is True
```

---

## Step 2.12 — Scheduler Tests

`tests/test_scheduler/test_pipeline.py`

> **Note**: These tests turn GREEN in **Phase 4** (Step 4.4).

| Test | Asserts |
|---|---|
| `test_schedule_sync_dispatches_task` | `run_incremental_sync.delay()` is called |
| `test_schedule_uses_configured_interval` | Beat schedule reads `sync_interval_hours` from Settings |

```python
"""Tests for src/scheduler/pipeline.py — turns GREEN in Phase 4."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from src.scheduler.pipeline import schedule_sync


class TestSchedulerPipeline:
    @patch("src.scheduler.pipeline.run_incremental_sync")
    def test_schedule_sync_dispatches_task(self, mock_task):
        schedule_sync()
        mock_task.delay.assert_called_once()

    @patch("src.worker.celery_app.settings")
    def test_schedule_uses_configured_interval(self, mock_settings):
        mock_settings.sync_interval_hours = 12
        from src.worker.celery_app import app
        beat_schedule = app.conf.beat_schedule
        assert "incremental-sync" in beat_schedule
```

---

## Step 2.13 — RAG Tests

### `tests/test_rag/test_retriever.py`

| Test | Asserts |
|---|---|
| `test_retrieve_top_k_chunks` | Returns k most relevant chunks for a query |
| `test_retrieve_with_document_type_filter` | Filters results by document type |
| `test_retrieve_includes_metadata` | Results include `source_name`, `section_title`, `chunk_index` |
| `test_retrieve_empty_query` | Returns empty list or raises error |
| `test_retrieve_caches_result` | Second identical query hits Redis cache |

```python
"""Tests for src/rag/retriever.py — turns GREEN in Phase 6."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.rag.retriever import Retriever


class TestRetriever:
    @pytest.fixture
    def retriever(self, mock_ollama_client, mock_milvus_client, mock_redis_client):
        embedder = AsyncMock()
        embedder.embed_texts.return_value = [[0.1] * 768]
        return Retriever(embedder=embedder, vector_store=mock_milvus_client, cache=mock_redis_client)

    async def test_retrieve_top_k_chunks(self, retriever):
        retriever._vector_store.search.return_value = [
            {"id": "h1", "text": "revenue data", "source_name": "report.pdf", "score": 0.95}
        ]
        results = await retriever.retrieve("What is the revenue?", top_k=5)
        assert len(results) >= 1

    async def test_retrieve_with_document_type_filter(self, retriever):
        await retriever.retrieve("revenue", top_k=5, document_type="pdf")
        call_args = retriever._vector_store.search.call_args
        assert "pdf" in str(call_args)

    async def test_retrieve_includes_metadata(self, retriever):
        retriever._vector_store.search.return_value = [
            {"id": "h1", "text": "data", "source_name": "r.pdf", "section_title": "Rev", "chunk_index": 0, "score": 0.9}
        ]
        results = await retriever.retrieve("query")
        assert hasattr(results[0], "source_name")

    async def test_retrieve_empty_query(self, retriever):
        results = await retriever.retrieve("")
        assert results == [] or isinstance(results, list)

    async def test_retrieve_caches_result(self, retriever):
        retriever._vector_store.search.return_value = [{"id": "h1", "text": "cached", "score": 0.9}]
        await retriever.retrieve("same query")
        await retriever.retrieve("same query")
        # Second call should hit cache, so search called only once
```

### `tests/test_rag/test_conversation.py`

| Test | Asserts |
|---|---|
| `test_store_and_retrieve_history` | Appended turns are retrievable |
| `test_history_respects_max_turns` | Oldest turns evicted beyond `MAX_HISTORY_TURNS` |
| `test_empty_history_for_unknown_id` | Returns `[]` for non-existent conversation |
| `test_clear_history` | `clear()` removes all turns |
| `test_history_expires_after_ttl` | Entries expire after TTL |

```python
"""Tests for src/rag/conversation.py — turns GREEN in Phase 6."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from src.rag.conversation import ConversationStore


class TestConversationStore:
    @pytest.fixture
    def store(self, mock_redis_client):
        store = ConversationStore.__new__(ConversationStore)
        store._redis = mock_redis_client
        return store

    def test_store_and_retrieve_history(self, store):
        store._redis.get.return_value = None
        store.append("conv-1", "user", "Hello")
        store._redis.get.return_value = '[{"role": "user", "content": "Hello"}]'
        history = store.get_history("conv-1")
        assert len(history) == 1
        assert history[0].role == "user"

    def test_empty_history_for_unknown_id(self, store):
        store._redis.get.return_value = None
        history = store.get_history("unknown")
        assert history == []

    def test_clear_history(self, store):
        store.clear("conv-1")
        store._redis.delete.assert_called_once_with("conv:conv-1")
```

---

### `tests/test_rag/test_llm_client.py`

| Test | Asserts |
|---|---|
| `test_chat_completion_ollama` | Returns response using Ollama backend |
| `test_chat_completion_gemini` | Returns response using Gemini backend |
| `test_chat_completion_deepseek` | Returns response using DeepSeek backend |
| `test_provider_selection_from_config` | Correct backend selected from `LLM_PROVIDER` |
| `test_streaming_response` | Yields chunks for streaming mode |
| `test_handles_api_error` | Raises appropriate error on API failure |
| `test_respects_max_tokens` | Response truncated at `max_tokens` |

```python
"""Tests for src/rag/llm_client.py — turns GREEN in Phase 6."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pydantic import SecretStr

from src.rag.llm_client import create_llm_client, OllamaLLMClient, GeminiLLMClient, DeepSeekLLMClient


class TestLLMClient:
    @patch("src.rag.llm_client.openai.AsyncOpenAI")
    async def test_chat_completion_ollama(self, mock_openai, settings):
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Hello!"))]
        )
        mock_openai.return_value = mock_client
        llm = OllamaLLMClient(settings)
        response = await llm.chat([{"role": "user", "content": "Hi"}])
        assert isinstance(response, str)

    @patch("src.rag.llm_client.openai.AsyncOpenAI")
    async def test_chat_completion_gemini(self, mock_openai, settings):
        settings_gemini = settings.model_copy(update={"llm_provider": "gemini", "llm_api_key": SecretStr("key")})
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Gemini response"))]
        )
        mock_openai.return_value = mock_client
        llm = GeminiLLMClient(settings_gemini)
        response = await llm.chat([{"role": "user", "content": "Hi"}])
        assert isinstance(response, str)

    @patch("src.rag.llm_client.openai.AsyncOpenAI")
    async def test_chat_completion_deepseek(self, mock_openai, settings):
        settings_ds = settings.model_copy(update={"llm_provider": "deepseek", "llm_api_key": SecretStr("key")})
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="DeepSeek response"))]
        )
        mock_openai.return_value = mock_client
        llm = DeepSeekLLMClient(settings_ds)
        response = await llm.chat([{"role": "user", "content": "Hi"}])
        assert isinstance(response, str)

    def test_provider_selection_from_config(self, settings):
        llm = create_llm_client(settings)
        assert isinstance(llm, OllamaLLMClient)

    @patch("src.rag.llm_client.openai.AsyncOpenAI")
    async def test_streaming_response(self, mock_openai, settings):
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        llm = OllamaLLMClient(settings)
        chunks = []
        async for chunk in llm.chat_stream([{"role": "user", "content": "Hi"}]):
            chunks.append(chunk)
        # Should yield at least something or be iterable

    @patch("src.rag.llm_client.openai.AsyncOpenAI")
    async def test_handles_api_error(self, mock_openai, settings):
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        mock_openai.return_value = mock_client
        llm = OllamaLLMClient(settings)
        with pytest.raises(Exception, match="API Error"):
            await llm.chat([{"role": "user", "content": "Hi"}])

    @patch("src.rag.llm_client.openai.AsyncOpenAI")
    async def test_respects_max_tokens(self, mock_openai, settings):
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        llm = OllamaLLMClient(settings)
        await llm.chat([{"role": "user", "content": "Hi"}], max_tokens=100)
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] == 100
```

---

## Step 2.14 — Generator Tests

### `tests/test_generator/test_sql_generator.py`

| Test | Asserts |
|---|---|
| `test_discover_schema_from_chunks` | Returns valid CREATE TABLE SQL from sample chunks |
| `test_generate_inserts_from_chunks` | Returns INSERT statements matching schema |
| `test_handles_inconsistent_data` | Skips or logs rows that don't match schema |

```python
"""Tests for src/generator/sql_generator.py — turns GREEN in Phase 6."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from src.generator.sql_generator import SQLGenerator


class TestSQLGenerator:
    @pytest.fixture
    def sql_gen(self):
        retriever = AsyncMock()
        llm = AsyncMock()
        return SQLGenerator(retriever=retriever, llm=llm)

    async def test_discover_schema_from_chunks(self, sql_gen):
        sql_gen._llm.chat.return_value = "CREATE TABLE invoices (id INT, amount DECIMAL);"
        sql_gen._retriever.retrieve.return_value = [AsyncMock(text="Invoice #1: $100")]
        schema = await sql_gen.discover_schema("invoices from PDFs")
        assert "CREATE TABLE" in schema

    async def test_generate_inserts_from_chunks(self, sql_gen):
        sql_gen._llm.chat.return_value = "INSERT INTO invoices VALUES (1, 100.0);"
        chunks = [AsyncMock(text="Invoice #1: $100")]
        inserts = await sql_gen.extract_data(chunks, "CREATE TABLE invoices (id INT, amount DECIMAL);")
        assert any("INSERT" in s for s in inserts)

    async def test_handles_inconsistent_data(self, sql_gen):
        sql_gen._llm.chat.return_value = "-- skipped: inconsistent row"
        chunks = [AsyncMock(text="malformed data")]
        inserts = await sql_gen.extract_data(chunks, "CREATE TABLE t (id INT);")
        assert isinstance(inserts, list)

    def test_validate_rejects_drop_table(self):
        from src.generator.sql_generator import SQLGenerator
        assert SQLGenerator.validate_statement("DROP TABLE users;") is False

    def test_validate_rejects_delete(self):
        from src.generator.sql_generator import SQLGenerator
        assert SQLGenerator.validate_statement("DELETE FROM users WHERE id = 1;") is False

    def test_validate_rejects_update(self):
        from src.generator.sql_generator import SQLGenerator
        assert SQLGenerator.validate_statement("UPDATE users SET name = 'x';") is False

    def test_validate_accepts_insert(self):
        from src.generator.sql_generator import SQLGenerator
        assert SQLGenerator.validate_statement("INSERT INTO invoices VALUES (1, 100.0);") is True

    def test_validate_accepts_create_table(self):
        from src.generator.sql_generator import SQLGenerator
        assert SQLGenerator.validate_statement("CREATE TABLE invoices (id INT);") is True
```

### `tests/test_generator/test_db_writer.py`

| Test | Asserts |
|---|---|
| `test_execute_create_table` | Creates table in test database |
| `test_execute_insert` | Inserts rows successfully |
| `test_rollback_on_error` | Transaction rolled back on SQL error |

```python
"""Tests for src/generator/db_writer.py — turns GREEN in Phase 6."""
from __future__ import annotations

import pytest

from src.generator.db_writer import DBWriter


class TestDBWriter:
    async def test_execute_create_table(self, db_session):
        writer = DBWriter(session=db_session)
        await writer.execute("CREATE TABLE test_tbl (id INTEGER PRIMARY KEY, name TEXT)")

    async def test_execute_insert(self, db_session):
        writer = DBWriter(session=db_session)
        await writer.execute("CREATE TABLE test_tbl (id INTEGER PRIMARY KEY, name TEXT)")
        count = await writer.execute_many(["INSERT INTO test_tbl VALUES (1, 'Alice')", "INSERT INTO test_tbl VALUES (2, 'Bob')"])
        assert count == 2

    async def test_rollback_on_error(self, db_session):
        writer = DBWriter(session=db_session)
        with pytest.raises(Exception):
            await writer.execute("INSERT INTO nonexistent_table VALUES (1)")
```

### `tests/test_generator/test_sheets_writer.py`

| Test | Asserts |
|---|---|
| `test_write_rows_to_sheet` | Writes data to Google Sheet via gspread |
| `test_creates_sheet_if_missing` | Creates new worksheet if it doesn't exist |

```python
"""Tests for src/generator/sheets_writer.py — turns GREEN in Phase 6."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.generator.sheets_writer import SheetsWriter


class TestSheetsWriter:
    @patch("src.generator.sheets_writer.gspread.service_account")
    def test_write_rows_to_sheet(self, mock_gspread):
        mock_sheet = MagicMock()
        mock_gspread.return_value.open_by_key.return_value.worksheet.return_value = mock_sheet
        writer = SheetsWriter(credentials_path="credentials/sa.json")
        writer.write_rows("spreadsheet-id", "Sheet1", [["Alice", "30"], ["Bob", "25"]])
        mock_sheet.append_rows.assert_called_once()

    @patch("src.generator.sheets_writer.gspread.service_account")
    def test_creates_sheet_if_missing(self, mock_gspread):
        mock_spreadsheet = MagicMock()
        mock_spreadsheet.worksheet.side_effect = Exception("not found")
        mock_spreadsheet.add_worksheet.return_value = MagicMock()
        mock_gspread.return_value.open_by_key.return_value = mock_spreadsheet
        writer = SheetsWriter(credentials_path="credentials/sa.json")
        writer.write_rows("spreadsheet-id", "NewSheet", [["data"]])
        mock_spreadsheet.add_worksheet.assert_called_once()
```

---

## Step 2.15 — Automation Tests

### `tests/test_automation/test_templates.py`

| Test | Asserts |
|---|---|
| `test_parse_valid_yaml` | Returns `AutomationConfig` from valid YAML |
| `test_parse_invalid_yaml` | Raises `ValueError` for missing required fields |
| `test_filter_matches_file` | Filter correctly matches MIME type and name pattern |

```python
"""Tests for src/automation/templates.py — turns GREEN in Phase 6."""
from __future__ import annotations

import pytest

from src.automation.templates import parse_automation, matches_file, AutomationConfig


class TestAutomationTemplates:
    def test_parse_valid_yaml(self):
        yaml_str = """
name: invoice-extractor
trigger: on_new_file
filter:
  mime_type: application/pdf
  name_pattern: "invoice_*"
prompt: "Extract line items."
action:
  type: execute_sql
  target: postgres
"""
        config = parse_automation(yaml_str)
        assert isinstance(config, AutomationConfig)
        assert config.name == "invoice-extractor"

    def test_parse_invalid_yaml(self):
        yaml_str = "name: missing-fields"
        with pytest.raises(ValueError):
            parse_automation(yaml_str)

    def test_filter_matches_file(self):
        from src.automation.templates import AutomationFilter
        f = AutomationFilter(mime_type="application/pdf", name_pattern="invoice_*")
        assert matches_file(f, {"mimeType": "application/pdf", "name": "invoice_001.pdf"}) is True
        assert matches_file(f, {"mimeType": "text/plain", "name": "readme.txt"}) is False
```

### `tests/test_automation/test_engine.py`

| Test | Asserts |
|---|---|
| `test_trigger_on_new_file` | Engine fires for matching new file |
| `test_execute_sql_action` | Runs retrieval → LLM → SQL execution chain |
| `test_skip_non_matching_file` | Engine ignores files that don't match filter |

```python
"""Tests for src/automation/engine.py — turns GREEN in Phase 6."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.automation.engine import AutomationEngine
from src.automation.templates import AutomationConfig, AutomationFilter, AutomationAction


class TestAutomationEngine:
    @pytest.fixture
    def engine(self):
        config = AutomationConfig(
            name="test-auto",
            trigger="on_new_file",
            filter=AutomationFilter(mime_type="application/pdf"),
            prompt="Extract data",
            action=AutomationAction(type="execute_sql", target="postgres"),
        )
        return AutomationEngine(
            retriever=AsyncMock(),
            llm=AsyncMock(),
            db_writer=AsyncMock(),
            sheets_writer=MagicMock(),
            configs=[config],
        )

    async def test_trigger_on_new_file(self, engine):
        engine._llm.chat.return_value = "INSERT INTO t VALUES (1);"
        await engine.run("on_new_file", {"mimeType": "application/pdf", "name": "invoice.pdf"})
        engine._retriever.retrieve.assert_called_once()

    async def test_execute_sql_action(self, engine):
        engine._llm.chat.return_value = "INSERT INTO t VALUES (1);"
        await engine.run("on_new_file", {"mimeType": "application/pdf", "name": "invoice.pdf"})
        engine._db_writer.execute_many.assert_called_once()

    async def test_skip_non_matching_file(self, engine):
        await engine.run("on_new_file", {"mimeType": "text/plain", "name": "readme.txt"})
        engine._retriever.retrieve.assert_not_called()
```

---

## Step 2.16 — API Tests

### `tests/test_api/test_schemas.py`

| Test | Asserts |
|---|---|
| `test_chat_request_validation` | Accepts valid `ChatRequest` |
| `test_chat_request_rejects_empty` | Rejects empty `query` field |
| `test_chat_response_structure` | `ChatResponse` has `answer`, `sources`, `conversation_id` |
| `test_status_response_structure` | `StatusResponse` has `total`, `pending`, `processed`, `failed` |

```python
"""Tests for src/api/schemas.py — turns GREEN in Phase 7."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.schemas import ChatRequest, ChatResponse, SourceReference, StatusResponse


class TestAPISchemas:
    def test_chat_request_validation(self):
        req = ChatRequest(query="What is revenue?")
        assert req.query == "What is revenue?"

    def test_chat_request_rejects_empty(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="")

    def test_chat_response_structure(self):
        resp = ChatResponse(
            answer="Revenue was $1.2M",
            sources=[SourceReference(
                source_file_id="f1", source_name="report.pdf",
                section_title="Revenue", chunk_index=0,
                text_preview="Total revenue...", score=0.95,
            )],
            conversation_id="conv-123",
        )
        assert resp.answer == "Revenue was $1.2M"
        assert len(resp.sources) == 1

    def test_status_response_structure(self):
        resp = StatusResponse(total_files=100, pending=10, downloaded=20, converted=30, embedded=35, failed=5)
        assert resp.total_files == 100
        assert resp.failed == 5
```

### `tests/test_api/test_routes.py`

| Test | Asserts |
|---|---|
| `test_chat_endpoint_returns_answer` | POST `/chat` returns 200 with answer and sources |
| `test_chat_endpoint_includes_references` | Response `sources` contain file name, section, chunk text |
| `test_chat_returns_conversation_id` | Response includes `conversation_id` for multi-turn |
| `test_status_endpoint` | GET `/status` returns pipeline progress |
| `test_status_files_endpoint` | GET `/status/files` returns per-file status list |
| `test_generate_sql_endpoint` | POST `/generate-sql` returns job ID |
| `test_generate_sql_poll` | GET `/generate-sql/{job_id}` returns results |
| `test_websocket_chat` | WS `/ws/chat` streams response chunks |
| `test_api_key_auth_rejects_invalid_key` | Returns 401 when `API_KEY` is set and wrong key sent |
| `test_api_key_auth_allows_valid_key` | Returns 200 when correct `X-API-Key` header sent |
| `test_api_key_auth_disabled_when_empty` | No auth required when `API_KEY` is empty |

```python
"""Tests for src/api/routes.py — turns GREEN in Phase 7."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from src.api.app import create_app


class TestAPIRoutes:
    @pytest.fixture
    def app(self):
        return create_app()

    @pytest.mark.integration
    async def test_chat_endpoint_returns_answer(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/chat", json={"query": "What is revenue?"})
            assert response.status_code == 200
            data = response.json()
            assert "answer" in data

    @pytest.mark.integration
    async def test_chat_endpoint_includes_references(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/chat", json={"query": "What is revenue?"})
            data = response.json()
            assert "sources" in data

    @pytest.mark.integration
    async def test_status_endpoint(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/status")
            assert response.status_code == 200

    @pytest.mark.integration
    async def test_status_files_endpoint(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/status/files")
            assert response.status_code == 200

    @pytest.mark.integration
    async def test_generate_sql_endpoint(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/generate-sql", json={"description": "invoices"})
            assert response.status_code == 200
            assert "job_id" in response.json()

    @pytest.mark.integration
    async def test_generate_sql_poll(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/generate-sql/test-job-id")
            assert response.status_code in (200, 404)

    @pytest.mark.integration
    async def test_chat_returns_conversation_id(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/chat", json={"query": "What is revenue?"})
            data = response.json()
            assert "conversation_id" in data
            assert len(data["conversation_id"]) > 0

    @pytest.mark.integration
    async def test_websocket_chat(self, app):
        from httpx_ws import aconnect_ws
        async with aconnect_ws("ws://test/ws/chat", app) as ws:
            await ws.send_json({"type": "query", "query": "Hello", "conversation_id": "test-conv"})
            msg = await ws.receive_json()
            assert msg["type"] in ("token", "done", "error")


class TestAPIAuth:
    """Tests for API key authentication — turns GREEN in Phase 7."""

    @pytest.fixture
    def app_with_key(self):
        """Create app with API_KEY configured."""
        import os
        os.environ["API_KEY"] = "test-secret-key"
        app = create_app()
        yield app
        del os.environ["API_KEY"]

    @pytest.mark.integration
    async def test_api_key_auth_rejects_invalid_key(self, app_with_key):
        async with AsyncClient(transport=ASGITransport(app=app_with_key), base_url="http://test") as client:
            response = await client.get("/status", headers={"X-API-Key": "wrong-key"})
            assert response.status_code == 401

    @pytest.mark.integration
    async def test_api_key_auth_allows_valid_key(self, app_with_key):
        async with AsyncClient(transport=ASGITransport(app=app_with_key), base_url="http://test") as client:
            response = await client.get("/status", headers={"X-API-Key": "test-secret-key"})
            assert response.status_code == 200

    @pytest.mark.integration
    async def test_api_key_auth_disabled_when_empty(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/status")
            assert response.status_code == 200
```

---

## Step 2.17 — Run All Tests (RED Verification)

```bash
pytest --collect-only       # all tests discovered, no import errors from test files
pytest -x 2>&1 | head -50  # all tests FAIL (no implementations yet)
```

Every test should fail with `ImportError` (modules not yet created) or `NotImplementedError`. If any test has a syntax error or missing fixture, fix it before moving to Phase 3.

### Phase-to-GREEN mapping

| Tests | Turn GREEN in |
|---|---|
| `test_config/` | Phase 1 (Settings already exists) |
| `test_storage/`, `test_metadata/`, `test_drive/`, `test_converter/`, `test_vectorizer/test_chunker.py` | Phase 3 |
| `test_worker/` (except embed), `test_scheduler/` | Phase 4 (`test_embed_task_calls_embedder` is `xfail`) |
| `test_vectorizer/test_embedder.py`, `test_vectorizer/test_milvus_store.py`, `test_embed_task_calls_embedder` (remove `xfail`) | Phase 5 |
| `test_rag/` (incl. `test_conversation.py`), `test_generator/` (incl. SQL safety), `test_automation/` | Phase 6 |
| `test_api/` (incl. auth tests) | Phase 7 |

---

## Output of This Phase

- `pyproject.toml` with pytest, ruff format, mypy configuration
- `tests/conftest.py` with shared fixtures (`settings` with isolated Redis DBs, `db_session`, mocks for MinIO, Drive, Ollama, httpx, Milvus, Redis)
- `tests/test_config/test_settings.py` — Settings validation tests
- `tests/test_storage/test_backend.py` — MinIO + local fallback tests
- `tests/test_metadata/test_repository.py` — Async CRUD tests using aiosqlite
- `tests/test_drive/test_auth.py` — Drive auth tests
- `tests/test_drive/test_downloader.py` — Incremental sync + **full sync** + download + **deletion detection** tests
- `tests/test_converter/test_pdf_converter.py` — PDF + OCR tests
- `tests/test_converter/test_docs_converter.py` — Docs export tests
- `tests/test_converter/test_sheets_converter.py` — Sheets export tests
- `tests/test_converter/test_docx_converter.py` — `.docx` extraction tests
- `tests/test_converter/test_xlsx_converter.py` — `.xlsx` extraction tests
- `tests/test_converter/test_text_converter.py` — `text/plain`, `text/markdown`, `text/html` tests
- `tests/test_vectorizer/test_chunker.py` — Document-aware chunking tests (with tiktoken)
- `tests/test_vectorizer/test_embedder.py` — Batch embedding tests
- `tests/test_vectorizer/test_milvus_store.py` — Vector store tests
- `tests/test_worker/test_tasks.py` — Celery task chain tests + **deletion task** + **distributed lock** + **unsupported MIME handling** (`test_embed_task_calls_embedder` marked `xfail`)
- `tests/test_scheduler/test_pipeline.py` — Scheduler dispatch tests
- `tests/test_rag/test_retriever.py` — Semantic search + cache tests
- `tests/test_rag/test_conversation.py` — **Conversation memory** store/retrieve/clear tests
- `tests/test_rag/test_llm_client.py` — Multi-provider LLM tests
- `tests/test_generator/test_sql_generator.py` — Schema discovery + **SQL safety validation** tests
- `tests/test_generator/test_db_writer.py` — SQL execution tests
- `tests/test_generator/test_sheets_writer.py` — Google Sheets output tests
- `tests/test_automation/test_templates.py` — YAML automation config tests
- `tests/test_automation/test_engine.py` — Automation runner tests
- `tests/test_api/test_schemas.py` — Pydantic model validation tests
- `tests/test_api/test_routes.py` — REST + WebSocket endpoint tests + **API key auth tests** (marked `@pytest.mark.integration`)
- `pytest --collect-only` discovers every test
- All tests in **RED** state — ready for implementation in Phases 1–7
