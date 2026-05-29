from __future__ import annotations

import io

from minio import Minio

from .settings import Settings


class MinIOStorage:
    def __init__(self, settings: Settings) -> None:
        """Initialize the MinIO client with credentials and bucket names from settings.

        Args:
            settings: Application settings providing MinIO endpoint, credentials, and bucket names.
        """
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )
        self._raw_bucket = settings.minio_bucket_raw
        self._text_bucket = settings.minio_bucket_text

    def ensure_buckets(self) -> None:
        """Create the raw-files and converted-texts MinIO buckets if they do not already exist."""
        for bucket in [self._raw_bucket, self._text_bucket]:
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)

    def download_raw(self, key: str) -> bytes:
        """Download a raw file from MinIO and return its content as bytes.

        Args:
            key: MinIO object key within the raw-files bucket.

        Returns:
            Full file content as a bytes object.
        """
        response = self._client.get_object(self._raw_bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def upload_text(self, key: str, data: bytes) -> None:
        """Upload extracted text bytes to the converted-texts MinIO bucket.

        Args:
            key: MinIO object key to use for the uploaded text (typically '<file_id>.md').
            data: UTF-8 encoded text content to store.
        """
        self._client.put_object(
            bucket_name=self._text_bucket,
            object_name=key,
            data=io.BytesIO(data),
            length=len(data),
        )
