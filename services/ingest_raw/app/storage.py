from __future__ import annotations

import io

from minio import Minio

from .settings import Settings


class MinIOStorage:
    def __init__(self, settings: Settings) -> None:
        """Initialize the MinIO client with credentials and the raw-files bucket name from settings.

        Args:
            settings: Application settings providing MinIO endpoint, credentials, and bucket name.
        """
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )
        self._bucket = settings.minio_bucket_raw

    def ensure_bucket(self) -> None:
        """Create the raw-files MinIO bucket if it does not already exist."""
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def upload_raw(self, key: str, data: bytes) -> None:
        """Upload raw file bytes to the raw-files MinIO bucket.

        Args:
            key: MinIO object key, typically '<file_id>/<file_name>'.
            data: Raw file content to store.
        """
        self._client.put_object(
            bucket_name=self._bucket,
            object_name=key,
            data=io.BytesIO(data),
            length=len(data),
        )
