from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock


SERVICE_ROOT = Path(__file__).resolve().parents[1]
for module_name in [name for name in list(sys.modules) if name == "app" or name.startswith("app.")]:
    del sys.modules[module_name]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.db import RawCandidate
from app.service import ExtractTextService


def test_extract_text_service_skips_when_lock_is_held():
    """Verify that run_once returns zero counts without processing when the advisory lock is already held."""
    settings = MagicMock()
    settings.extract_text_lock_id = 77
    repo = MagicMock()
    storage = MagicMock()
    repo.try_acquire_lock.return_value = False

    service = ExtractTextService(settings=settings, repo=repo, storage=storage)
    result = service.run_once()

    assert result == {"scanned": 0, "updated": 0, "failed": 0}
    repo.release_lock.assert_not_called()


def test_extract_text_service_processes_changed_raw_files():
    """Verify that run_once downloads, extracts, uploads, and marks a changed raw file as ready."""
    settings = MagicMock()
    settings.extract_text_lock_id = 77
    settings.extract_text_batch_size = 100
    repo = MagicMock()
    storage = MagicMock()
    repo.try_acquire_lock.return_value = True
    repo.list_raw_changed_candidates.return_value = [
        RawCandidate(
            drive_file_id="f1",
            name="sample.txt",
            mime_type="text/plain",
            minio_raw_key="f1/sample.txt",
            raw_checksum="abc123",
        )
    ]
    storage.download_raw.return_value = b"hello world"

    service = ExtractTextService(settings=settings, repo=repo, storage=storage)
    result = service.run_once()

    assert result["updated"] == 1
    storage.upload_text.assert_called_once()
    uploaded_key = storage.upload_text.call_args.args[0]
    assert uploaded_key == "f1.md"
    repo.mark_text_ready.assert_called_once()
    assert repo.mark_text_ready.call_args.kwargs["minio_text_key"] == "f1.md"
    repo.release_lock.assert_called_once_with(77)
