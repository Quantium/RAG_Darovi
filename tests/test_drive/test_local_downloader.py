from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from src.drive.local_downloader import LocalFolderDownloader


def _build_settings(tmp_path: Path) -> Settings:
    return Settings(ingest_source="local", local_source_folder=str(tmp_path))


@pytest.mark.asyncio
async def test_incremental_sync_detects_local_changes_and_deletions(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.txt").write_text("hello", encoding="utf-8")

    metadata_repo = MagicMock()
    metadata_repo.list_by_status.return_value = [SimpleNamespace(drive_file_id="old/deleted.txt", drive_modified_at=None)]
    metadata_repo.update_page_token = AsyncMock()

    downloader = LocalFolderDownloader(
        storage=MagicMock(),
        metadata_repo=metadata_repo,
        settings=_build_settings(docs),
    )

    changed, deleted = await downloader.incremental_sync()

    assert len(changed) == 1
    assert changed[0]["id"] == "notes.txt"
    assert deleted == ["old/deleted.txt"]


@pytest.mark.asyncio
async def test_download_file_uploads_local_file_and_updates_metadata(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    target = docs / "report.md"
    target.write_text("# Report", encoding="utf-8")

    storage = MagicMock()
    metadata_repo = AsyncMock()
    metadata_repo.get_file.return_value = None

    downloader = LocalFolderDownloader(storage=storage, metadata_repo=metadata_repo, settings=_build_settings(docs))
    key = await downloader.download_file(
        {
            "id": "report.md",
            "name": "report.md",
            "mimeType": "text/markdown",
            "modifiedTime": "2026-01-01T00:00:00Z",
            "localPath": str(target),
        }
    )

    assert key == "report.md"
    storage.upload.assert_called_once()
    metadata_repo.upsert_file.assert_called_once()
    metadata_repo.update_status.assert_called_once_with("report.md", "downloaded")
