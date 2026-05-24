from __future__ import annotations

import io

from minio import Minio

from .settings import Settings


class MinIOStorage:
    def __init__(self, settings: Settings) -> None:
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )
        self._raw_bucket = settings.minio_bucket_raw
        self._text_bucket = settings.minio_bucket_text

    def ensure_buckets(self) -> None:
        for bucket in [self._raw_bucket, self._text_bucket]:
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)

    def download_raw(self, key: str) -> bytes:
        response = self._client.get_object(self._raw_bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def upload_text(self, key: str, data: bytes) -> None:
        self._client.put_object(
            bucket_name=self._text_bucket,
            object_name=key,
            data=io.BytesIO(data),
            length=len(data),
        )
