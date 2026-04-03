"""Tests for src/worker/tasks.py — turns GREEN in Phase 4 (embed in Phase 5)."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock, AsyncMock, ANY

from src.worker.tasks import download_file, convert_file, embed_file, run_incremental_sync, delete_file_vectors
from src.worker.celery_app import RetryableTask # Import RetryableTask


class TestWorkerTasks:
    @patch("src.drive.auth.build_drive_service")
    @patch("src.drive.downloader.DriveDownloader")
    @patch("src.worker.tasks.build_metadata_repo")
    @patch("celery.app.task.request") # Patch the global request object
    def test_download_task_calls_downloader(self, mock_celery_request, mock_repo_builder, mock_dl_cls, mock_build_service):
        mock_celery_request.headers = {"trace_id": "test-trace-id"}
        mock_repo_builder.return_value = (MagicMock(), lambda: None)
        mock_dl = mock_dl_cls.return_value
        mock_dl.download_file = AsyncMock(return_value="raw-files/f1/test.pdf")
        
        result = download_file({"id": "f1", "name": "test.pdf", "mimeType": "application/pdf"})
        mock_dl.download_file.assert_called_once()
        assert "drive_file_id" in result

    @patch("src.worker.tasks.build_storage")
    @patch("src.converter.get_converter")
    @patch("src.worker.tasks.build_metadata_repo")
    @patch("celery.app.task.request") # Patch the global request object
    def test_convert_task_calls_converter(self, mock_celery_request, mock_repo_builder, mock_get_converter, mock_storage_builder):
        mock_celery_request.headers = {"trace_id": "test-trace-id"}
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

    @pytest.mark.xfail(reason="Placeholder until Phase 5 implements embed_file", strict=True)
    @patch("celery.app.task.request") # Patch the global request object
    def test_embed_task_calls_embedder(self, mock_celery_request):
        mock_celery_request.headers = {"trace_id": "test-trace-id"}
        result = embed_file({"drive_file_id": "f1", "minio_text_key": "texts/f1.txt", "name": "test.pdf", "document_type": "pdf"})
        assert result is not None

    def test_task_chain_download_convert_embed(self):
        from celery import chain
        pipeline = chain(download_file.s({}), convert_file.s(), embed_file.s())
        assert pipeline is not None

    @patch("src.drive.auth.build_drive_service")
    @patch("src.drive.downloader.DriveDownloader")
    @patch("src.worker.tasks.build_metadata_repo")
    @patch("celery.app.task.request") # Patch the global request object
    def test_task_retry_on_failure(self, mock_celery_request, mock_repo_builder, mock_dl_cls, mock_build_service):
        mock_celery_request.headers = {"trace_id": "test-trace-id"}
        mock_repo_builder.return_value = (MagicMock(), lambda: None)
        mock_dl = mock_dl_cls.return_value
        mock_dl.download_file.side_effect = ConnectionError("timeout")
        with pytest.raises(ConnectionError):
            download_file({"id": "f1", "name": "test.pdf", "mimeType": "application/pdf"})

    @patch("src.worker.task_helpers.SyncMetadataRepository")
    @patch("celery.app.task.request") # Patch the global request object for on_failure
    def test_task_marks_failed_after_max_retries(self, mock_celery_request, mock_repo_cls):
        mock_celery_request.headers = {"trace_id": "test-trace-id"} # For potential logging in on_failure
        mock_repo = mock_repo_cls.return_value
        
        task = RetryableTask()
        task.name = "test_task"
        # When Celery calls on_failure, 'self' is the task instance. We need to mock its request.
        # However, patching celery.app.task.request at the global level handles this correctly.
        task.on_failure(Exception("error"), "task_id", [{"id": "f1"}], {}, None)
        
        mock_repo.update_status.assert_called_with("f1", "failed", error_message="error")

    @patch("src.vectorizer.milvus_store.MilvusStore")
    @patch("src.worker.tasks.build_metadata_repo")
    @patch("src.worker.tasks.build_storage")
    @patch("celery.app.task.request") # Patch the global request object
    def test_delete_file_vectors_removes_all(self, mock_celery_request, mock_storage_builder, mock_repo_builder, mock_milvus_store_cls):
        mock_celery_request.headers = {"trace_id": "test-trace-id"}
        mock_repo = MagicMock()
        mock_repo_builder.return_value = (mock_repo, lambda: None)
        mock_milvus_store = mock_milvus_store_cls.return_value
        
        result = delete_file_vectors("f1")
        mock_repo.delete_file_record.assert_called_once_with("f1")
        mock_milvus_store.delete_by_source.assert_called_once_with("f1")
        assert result["deleted"] is True

    @patch("src.worker.tasks.redis.Redis")
    @patch("celery.app.task.request") # Patch the global request object
    def test_sync_acquires_distributed_lock(self, mock_celery_request, mock_redis_cls):
        mock_celery_request.headers = {"trace_id": "test-trace-id"}
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
    @patch("celery.app.task.request") # Patch the global request object
    def test_sync_dispatches_deletions(self, mock_celery_request, mock_delete_task, mock_dispatch, mock_redis_cls, mock_repo_builder, mock_dl_cls, mock_build_service):
        mock_celery_request.headers = {"trace_id": "test-trace-id"}
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
    @patch("celery.app.task.request") # Patch the global request object
    def test_convert_task_skips_unsupported_mime(self, mock_celery_request, mock_storage_builder, mock_repo_builder, mock_get_converter):
        mock_celery_request.headers = {"trace_id": "test-trace-id"}
        mock_repo = MagicMock()
        mock_repo_builder.return_value = (mock_repo, lambda: None)
        mock_get_converter.side_effect = ValueError("Unsupported")
        
        result = convert_file({
            "drive_file_id": "f1", "minio_raw_key": "raw/f1", "mime_type": "video/mp4", "name": "movie.mp4"
        })
        assert result.get("skipped") is True
        mock_repo.update_status.assert_called_with("f1", "skipped", error_message="Unsupported MIME: video/mp4")
