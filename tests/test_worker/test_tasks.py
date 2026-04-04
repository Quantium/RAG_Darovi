"""Tests for src/worker/tasks.py — turns GREEN in Phase 4 (embed in Phase 5)."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock, AsyncMock, ANY

from src.worker.tasks import download_file, convert_file, embed_file, run_incremental_sync, delete_file_vectors
from src.worker.celery_app import RetryableTask


class TestWorkerTasks:
    @patch("src.drive.auth.build_drive_service")
    @patch("src.drive.downloader.DriveDownloader")
    @patch("src.worker.tasks.build_metadata_repo")
    def test_download_task_calls_downloader(self, mock_repo_builder, mock_dl_cls, mock_build_service):
        mock_repo_builder.return_value = (MagicMock(), lambda: None)
        mock_dl = mock_dl_cls.return_value
        mock_dl.download_file = AsyncMock(return_value="raw-files/f1/test.pdf")
        
        result = download_file({"id": "f1", "name": "test.pdf", "mimeType": "application/pdf"})
        mock_dl.download_file.assert_called_once()
        assert "drive_file_id" in result

    @patch("src.worker.tasks.build_storage")
    @patch("src.converter.get_converter")
    @patch("src.worker.tasks.build_metadata_repo")
    def test_convert_task_calls_converter(self, mock_repo_builder, mock_get_converter, mock_storage_builder):
        mock_repo_builder.return_value = (MagicMock(), lambda: None)
        mock_storage = MagicMock()
        mock_storage_builder.return_value = mock_storage
        mock_storage.download.return_value = b"pdf bytes"
        
        mock_converter = MagicMock()
        mock_converter.convert.return_value = "extracted text"
        mock_get_converter.return_value = mock_converter
        
        result = convert_file({
            "drive_file_id": "f1", 
            "minio_raw_key": "raw-files/f1/test.pdf", 
            "mime_type": "application/pdf", 
            "name": "test.pdf"
        })
        assert "minio_text_key" in result
        mock_converter.convert.assert_called_once()

    def test_embed_task_calls_embedder(self):
        with patch("src.worker.tasks.build_settings") as mock_settings:
            with patch("src.worker.tasks.build_storage") as mock_storage_builder:
                with patch("src.worker.tasks.asyncio.run") as mock_run:
                    mock_storage = MagicMock()
                    mock_storage_builder.return_value = mock_storage
                    mock_storage.download.return_value = b"some text"
                    mock_run.return_value = 10 # chunk count
                    
                    result = embed_file({
                        "drive_file_id": "f1", 
                        "minio_text_key": "texts/f1.txt", 
                        "name": "test.pdf", 
                        "document_type": "pdf"
                    })
                    assert result["chunk_count"] == 10

    def test_task_chain_download_convert_embed(self):
        from celery import chain
        pipeline = chain(download_file.s({}), convert_file.s(), embed_file.s())
        assert pipeline is not None

    @patch("src.drive.auth.build_drive_service")
    @patch("src.drive.downloader.DriveDownloader")
    @patch("src.worker.tasks.build_metadata_repo")
    def test_task_retry_on_failure(self, mock_repo_builder, mock_dl_cls, mock_build_service):
        mock_repo_builder.return_value = (MagicMock(), lambda: None)
        mock_dl = mock_dl_cls.return_value
        mock_dl.download_file.side_effect = ConnectionError("timeout")
        with pytest.raises(ConnectionError):
            download_file({"id": "f1", "name": "test.pdf", "mimeType": "application/pdf"})

    @patch("src.worker.task_helpers.SyncMetadataRepository")
    def test_task_marks_failed_after_max_retries(self, mock_repo_cls):
        mock_repo = mock_repo_cls.return_value
        
        task = RetryableTask()
        task.name = "test_task"
        task.on_failure(Exception("error"), "task_id", [{"id": "f1"}], {}, None)
        
        mock_repo.update_status.assert_called_with("f1", "failed", error_message="error")

    @patch("src.vectorizer.milvus_store.MilvusStore")
    @patch("src.worker.tasks.build_metadata_repo")
    @patch("src.worker.tasks.build_storage")
    def test_delete_file_vectors_removes_all(self, mock_storage_builder, mock_repo_builder, mock_milvus_store_cls):
        mock_repo = MagicMock()
        mock_repo_builder.return_value = (mock_repo, lambda: None)
        mock_milvus_store = mock_milvus_store_cls.return_value
        
        result = delete_file_vectors("f1")
        mock_repo.delete_file_record.assert_called_once_with("f1")
        mock_milvus_store.delete_by_source.assert_called_once_with("f1")
        assert result["deleted"] is True

    @patch("src.worker.tasks.redis.Redis")
    def test_sync_acquires_distributed_lock(self, mock_redis_cls):
        mock_redis = mock_redis_cls.from_url.return_value
        mock_redis.set.return_value = False  # lock not acquired
        
        with patch("src.drive.auth.build_drive_service") as mock_build_service:
            run_incremental_sync()
            mock_build_service.assert_not_called()

    @patch("src.drive.auth.build_drive_service")
    @patch("src.drive.downloader.DriveDownloader")
    @patch("src.worker.tasks.build_metadata_repo")
    @patch("src.worker.tasks.redis.Redis")
    @patch("src.worker.tasks.dispatch_file_pipeline")
    @patch("src.worker.tasks.delete_file_vectors")
    def test_sync_dispatches_deletions(self, mock_delete_task, mock_dispatch, mock_redis_cls, mock_repo_builder, mock_dl_cls, mock_build_service):
        mock_redis_cls.from_url.return_value.set.return_value = True
        mock_repo_builder.return_value = (MagicMock(), lambda: None)
        
        mock_dl = mock_dl_cls.return_value
        mock_dl.incremental_sync = AsyncMock(return_value=([], ["deleted-id-1"]))
        
        run_incremental_sync()
        
        mock_delete_task.delay.assert_called_with("deleted-id-1", headers={"trace_id": ANY})
        mock_dispatch.assert_not_called()

    @patch("src.converter.get_converter")
    @patch("src.worker.tasks.build_metadata_repo")
    @patch("src.worker.tasks.build_storage")
    def test_convert_task_skips_unsupported_mime(self, mock_storage_builder, mock_repo_builder, mock_get_converter):
        mock_repo = MagicMock()
        mock_repo_builder.return_value = (mock_repo, lambda: None)
        mock_get_converter.side_effect = ValueError("Unsupported")
        
        result = convert_file({
            "drive_file_id": "f1", "minio_raw_key": "raw/f1", "mime_type": "video/mp4", "name": "movie.mp4"
        })
        assert result.get("skipped") is True
        mock_repo.update_status.assert_called_with("f1", "skipped", error_message="Unsupported MIME: video/mp4")
