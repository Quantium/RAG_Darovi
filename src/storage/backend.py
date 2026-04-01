from __future__ import annotations

import io
from pathlib import Path
from typing import Protocol

from minio import Minio

from config.settings import Settings


class StorageBackend(Protocol):
    def upload(self, bucket: str, key: str, data: bytes) -> None:
        ...

    def download(self, bucket: str, key: str) -> bytes:
        ...

    def exists(self, bucket: str, key: str) -> bool:
        ...

    def delete(self, bucket: str, key: str) -> None:
        ...

    def ensure_buckets(self) -> None:
        ...


class MinIOStorage:
    def __init__(self, settings: Settings, client: Minio | None = None) -> None:
        self._client = client or Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )
        self._bucket_raw = settings.minio_bucket_raw
        self._bucket_text = settings.minio_bucket_text

    def upload(self, bucket: str, key: str, data: bytes) -> None:
        self._client.put_object(
            bucket_name=bucket,
            object_name=key,
            data=io.BytesIO(data),
            length=len(data),
        )

    def download(self, bucket: str, key: str) -> bytes:
        response = self._client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, bucket: str, key: str) -> bool:
        try:
            self._client.stat_object(bucket, key)
            return True
        except Exception:
            return False

    def delete(self, bucket: str, key: str) -> None:
        self._client.remove_object(bucket, key)

    def ensure_buckets(self) -> None:
        for bucket in [self._bucket_raw, self._bucket_text]:
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)


class LocalStorage:
    def __init__(self, base_path: Path) -> None:
        self._base = base_path

    def upload(self, bucket: str, key: str, data: bytes) -> None:
        path = self._base / bucket / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def download(self, bucket: str, key: str) -> bytes:
        path = self._base / bucket / key
        return path.read_bytes()

    def exists(self, bucket: str, key: str) -> bool:
        return (self._base / bucket / key).exists()

    def delete(self, bucket: str, key: str) -> None:
        path = self._base / bucket / key
        if path.exists():
            path.unlink()

    def ensure_buckets(self) -> None:
        # Not strictly needed for local, but for protocol compatibility
        pass
