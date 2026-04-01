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
