from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock


SERVICE_ROOT = Path(__file__).resolve().parents[1]
for module_name in [name for name in list(sys.modules) if name == "app" or name.startswith("app.")]:
    del sys.modules[module_name]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.service import IngestRawService
from app.sources import SourceFile


def test_ingest_raw_service_updates_changed_files():
    settings = MagicMock()
    settings.ingest_raw_batch_size = 10
    repo = MagicMock()
    source = MagicMock()
    storage = MagicMock()

    source.list_files.return_value = [
        SourceFile(
            file_id="f1",
            name="test.pdf",
            mime_type="application/pdf",
            source_version="2026-05-15T16:00:00Z",
        )
    ]
    source.download_file.return_value = b"raw-bytes"
    repo.get_file.return_value = None

    service = IngestRawService(settings=settings, repo=repo, source=source, storage=storage)
    result = service.run_once()

    assert result["updated"] == 1
    storage.upload_raw.assert_called_once()
    repo.update_raw_stage.assert_called_once()


def test_ingest_raw_service_skips_unchanged_files():
    settings = MagicMock()
    settings.ingest_raw_batch_size = 10
    repo = MagicMock()
    source = MagicMock()
    storage = MagicMock()

    source_file = SourceFile(
        file_id="f1",
        name="test.pdf",
        mime_type="application/pdf",
        source_version="v1",
    )
    source.list_files.return_value = [source_file]
    repo.get_file.return_value = MagicMock(raw_status="synced", raw_source_version="v1")

    service = IngestRawService(settings=settings, repo=repo, source=source, storage=storage)
    result = service.run_once()

    assert result["updated"] == 0
    assert result["skipped"] == 1
    storage.upload_raw.assert_not_called()
