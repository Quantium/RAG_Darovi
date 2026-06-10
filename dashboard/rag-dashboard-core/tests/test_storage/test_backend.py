"""Tests for src/storage/backend.py — turns GREEN in Phase 3."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.storage.backend import MinIOStorage, LocalStorage


class TestMinIOStorage:
    def test_upload_file(self, mock_minio_client, settings):
        """Verify upload calls the MinIO client's put_object method."""
        storage = MinIOStorage(settings, client=mock_minio_client)
        storage.upload("raw-files", "test-key", b"content")
        mock_minio_client.put_object.assert_called_once()

    def test_download_file(self, mock_minio_client, settings):
        """Verify download reads and returns the object bytes from the mock MinIO client."""
        storage = MinIOStorage(settings, client=mock_minio_client)
        data = storage.download("raw-files", "test-key")
        assert data == b"file content"

    def test_file_exists(self, mock_minio_client, settings):
        """Verify exists returns True when stat_object succeeds on the mock client."""
        storage = MinIOStorage(settings, client=mock_minio_client)
        assert storage.exists("raw-files", "test-key") is True

    def test_delete_file(self, mock_minio_client, settings):
        """Verify delete calls the MinIO client's remove_object method."""
        storage = MinIOStorage(settings, client=mock_minio_client)
        storage.delete("raw-files", "test-key")
        mock_minio_client.remove_object.assert_called_once()

    def test_ensure_buckets_created(self, mock_minio_client, settings):
        """Verify ensure_buckets creates both buckets when they do not exist."""
        mock_minio_client.bucket_exists.return_value = False
        storage = MinIOStorage(settings, client=mock_minio_client)
        storage.ensure_buckets()
        assert mock_minio_client.make_bucket.call_count == 2

    def test_count_objects(self, mock_minio_client, settings):
        """Verify count_objects returns the correct number of objects from the mock listing."""
        mock_minio_client.list_objects.return_value = [MagicMock(), MagicMock()]
        storage = MinIOStorage(settings, client=mock_minio_client)
        assert storage.count_objects("raw-files") == 2

    def test_remove_all_objects(self, mock_minio_client, settings):
        """Verify remove_all_objects deletes each object and returns the count removed."""
        mock_minio_client.list_objects.return_value = [MagicMock(object_name="a"), MagicMock(object_name="b")]
        storage = MinIOStorage(settings, client=mock_minio_client)
        n = storage.remove_all_objects("raw-files")
        assert n == 2
        assert mock_minio_client.remove_object.call_count == 2

    def test_remove_objects_with_prefix(self, mock_minio_client, settings):
        """Verify remove_objects forwards the prefix and deletes only the listed objects."""
        mock_minio_client.list_objects.return_value = [
            MagicMock(object_name="ejemplo1/a"),
            MagicMock(object_name="ejemplo1/b"),
        ]
        storage = MinIOStorage(settings, client=mock_minio_client)
        n = storage.remove_objects("raw-files", prefix="ejemplo1/")
        assert n == 2
        assert mock_minio_client.remove_object.call_count == 2
        _, kwargs = mock_minio_client.list_objects.call_args
        assert kwargs.get("prefix") == "ejemplo1/"

    def test_remove_objects_public_excludes_other_tenants(self, mock_minio_client, settings):
        """Verify a public-tenant clear skips keys owned by other licitaciones (cross-tenant guard)."""
        mock_minio_client.list_objects.return_value = [
            MagicMock(object_name="legacy1.pdf"),
            MagicMock(object_name="legacy2.pdf"),
            MagicMock(object_name="ejemplo1/x.pdf"),
            MagicMock(object_name="otro/y.pdf"),
        ]
        storage = MinIOStorage(settings, client=mock_minio_client)
        n = storage.remove_objects("raw-files", prefix="", exclude_prefixes=("ejemplo1/", "otro/"))
        assert n == 2
        removed = {call.args[1] for call in mock_minio_client.remove_object.call_args_list}
        assert removed == {"legacy1.pdf", "legacy2.pdf"}


class TestLocalStorage:
    def test_local_fallback_upload(self, tmp_path, settings):
        """Verify LocalStorage.upload writes bytes to the expected filesystem path."""
        storage = LocalStorage(base_path=tmp_path)
        storage.upload("raw-files", "test-key", b"content")
        assert (tmp_path / "raw-files" / "test-key").read_bytes() == b"content"

    def test_local_fallback_download(self, tmp_path, settings):
        """Verify LocalStorage.download reads bytes from the expected filesystem path."""
        (tmp_path / "raw-files").mkdir()
        (tmp_path / "raw-files" / "test-key").write_bytes(b"content")
        storage = LocalStorage(base_path=tmp_path)
        assert storage.download("raw-files", "test-key") == b"content"
