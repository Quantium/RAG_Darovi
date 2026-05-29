from __future__ import annotations

from unittest.mock import patch


class TestTaskHelpers:
    @patch("src.worker.task_helpers.MinIOStorage")
    def test_build_storage_ensures_buckets(self, mock_storage_cls):
        """Verify build_storage calls ensure_buckets and returns the storage instance."""
        from src.worker.task_helpers import build_storage

        storage = mock_storage_cls.return_value

        result = build_storage()

        storage.ensure_buckets.assert_called_once()
        assert result is storage
