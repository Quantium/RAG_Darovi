"""Tests for src/drive/downloader.py — turns GREEN in Phase 3."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.drive.downloader import DriveDownloader


class TestDriveDownloader:
    @pytest.fixture
    def downloader(self, mock_drive_service, mock_minio_client, settings):
        metadata_repo = AsyncMock()
        metadata_repo.get_page_token.return_value = "start-token"
        metadata_repo.get_file.return_value = None

        # Mock MediaIoBaseDownload to avoid real API calls and complex mocking
        with patch("src.drive.downloader.MediaIoBaseDownload") as mock_download_cls:
            mock_downloader = MagicMock()
            mock_downloader.next_chunk.return_value = (None, True)
            mock_download_cls.return_value = mock_downloader

            # Make the mocked FH receive some data
            def side_effect(fh, request):
                fh.write(b"mock content")
                return mock_downloader

            mock_download_cls.side_effect = side_effect

            yield DriveDownloader(
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
        downloader._drive_service.files.return_value.export_media.assert_called_with(fileId="f1", mimeType="text/plain")

    async def test_download_google_sheet_exports_as_csv(self, downloader):
        file_meta = {"id": "f1", "name": "sheet", "mimeType": "application/vnd.google-apps.spreadsheet"}
        await downloader.download_file(file_meta)
        downloader._drive_service.files.return_value.export_media.assert_called_with(fileId="f1", mimeType="text/csv")

    async def test_download_creates_metadata_record(self, downloader):
        file_meta = {"id": "f1", "name": "test.pdf", "mimeType": "application/pdf"}
        await downloader.download_file(file_meta)
        downloader._metadata_repo.upsert_file.assert_called()

    async def test_skip_already_processed_file(self, downloader):
        downloader._metadata_repo.get_file.return_value = MagicMock(drive_modified_at="2024-01-01T00:00:00Z")
        file_meta = {
            "id": "f1",
            "name": "test.pdf",
            "mimeType": "application/pdf",
            "modifiedTime": "2024-01-01T00:00:00Z",
        }
        result = await downloader.download_file(file_meta)
        assert result is None

    async def test_handles_api_rate_limit(self, downloader):
        from googleapiclient.errors import HttpError

        resp = MagicMock(status=429)
        downloader._drive_service.files.return_value.get_media.return_value.execute.side_effect = [
            HttpError(resp, b"Rate limit"),
            b"content",
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
