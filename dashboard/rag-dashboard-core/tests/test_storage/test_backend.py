"""Tests for src/storage/backend.py — turns GREEN in Phase 3."""

from __future__ import annotations

from unittest.mock import MagicMock

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

    def test_count_objects(self, mock_minio_client, settings):
        mock_minio_client.list_objects.return_value = [MagicMock(), MagicMock()]
        storage = MinIOStorage(settings, client=mock_minio_client)
        assert storage.count_objects("raw-files") == 2

    def test_remove_all_objects(self, mock_minio_client, settings):
        mock_minio_client.list_objects.return_value = [MagicMock(object_name="a"), MagicMock(object_name="b")]
        storage = MinIOStorage(settings, client=mock_minio_client)
        n = storage.remove_all_objects("raw-files")
        assert n == 2
        assert mock_minio_client.remove_object.call_count == 2


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
