from __future__ import annotations

import io
from pathlib import Path
from typing import Protocol

from minio import Minio

from config.settings import Settings


class StorageBackend(Protocol):
    def upload(self, bucket: str, key: str, data: bytes) -> None: ...

    def download(self, bucket: str, key: str) -> bytes: ...

    def exists(self, bucket: str, key: str) -> bool: ...

    def delete(self, bucket: str, key: str) -> None: ...

    def ensure_buckets(self) -> None: ...


class MinIOStorage:
    def __init__(self, settings: Settings, client: Minio | None = None) -> None:
        """Initialize the MinIO storage backend with credentials from settings.

        Args:
            settings: Application settings providing MinIO endpoint, credentials, and bucket names.
            client: Optional pre-built Minio client (useful for testing).
        """
        self._client = client or Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )
        self._bucket_raw = settings.minio_bucket_raw
        self._bucket_text = settings.minio_bucket_text

    def upload(self, bucket: str, key: str, data: bytes) -> None:
        """Upload bytes to a MinIO bucket under the given key.

        Args:
            bucket: Destination MinIO bucket name.
            key: Object key to store the data under.
            data: Raw bytes to upload.
        """
        self._client.put_object(
            bucket_name=bucket,
            object_name=key,
            data=io.BytesIO(data),
            length=len(data),
        )

    def download(self, bucket: str, key: str) -> bytes:
        """Download an object from a MinIO bucket and return its content.

        Args:
            bucket: Source MinIO bucket name.
            key: Object key to retrieve.

        Returns:
            Full object content as bytes.
        """
        response = self._client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, bucket: str, key: str) -> bool:
        """Return True if an object with the given key exists in the bucket.

        Args:
            bucket: MinIO bucket name to check.
            key: Object key to verify.

        Returns:
            True if the object exists, False otherwise.
        """
        try:
            self._client.stat_object(bucket, key)
            return True
        except Exception:
            return False

    def delete(self, bucket: str, key: str) -> None:
        """Delete a single object from a MinIO bucket.

        Args:
            bucket: MinIO bucket name.
            key: Object key to delete.
        """
        self._client.remove_object(bucket, key)

    def ensure_buckets(self) -> None:
        """Create the raw-files and converted-texts MinIO buckets if they do not already exist."""
        for bucket in [self._bucket_raw, self._bucket_text]:
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)

    def count_objects(self, bucket: str, prefix: str = "") -> int:
        """Count objects in a MinIO bucket, optionally restricted to a key prefix.

        Args:
            bucket: MinIO bucket name to count.
            prefix: Key prefix (e.g. a licitación's ``<slug>/``); empty counts the whole bucket.

        Returns:
            Number of objects under the prefix.
        """
        return sum(1 for _ in self._client.list_objects(bucket, prefix=prefix or None, recursive=True))

    def remove_all_objects(self, bucket: str) -> int:
        """Delete every object in a MinIO bucket and return the count removed.

        Args:
            bucket: MinIO bucket name to clear.

        Returns:
            Number of objects that were deleted.
        """
        removed = 0
        objects = list(self._client.list_objects(bucket, recursive=True))
        for obj in objects:
            self._client.remove_object(bucket, obj.object_name)
            removed += 1
        return removed

    def remove_objects(
        self, bucket: str, prefix: str = "", exclude_prefixes: tuple[str, ...] = ()
    ) -> int:
        """Delete objects under a key prefix, preserving any owned by other licitaciones.

        Scopes a destructive clear to a single tenant. A real licitación passes its
        ``<slug>/`` prefix, which is self-contained. The public/legacy tenant passes an
        empty prefix plus the ``<slug>/`` prefixes of every *other* licitación in
        ``exclude_prefixes``, so only the flat legacy objects are removed and no other
        tenant's keys are ever touched. This is the cross-tenant guard that
        :meth:`remove_all_objects` lacks.

        Args:
            bucket: MinIO bucket name.
            prefix: Key prefix to restrict deletion to ('' = whole bucket, minus excludes).
            exclude_prefixes: Key prefixes to preserve (other tenants' '<slug>/').

        Returns:
            Number of objects that were deleted.
        """
        removed = 0
        for obj in self._client.list_objects(bucket, prefix=prefix or None, recursive=True):
            name = obj.object_name
            if any(name.startswith(ex) for ex in exclude_prefixes):
                continue
            self._client.remove_object(bucket, name)
            removed += 1
        return removed


class LocalStorage:
    def __init__(self, base_path: Path) -> None:
        """Initialize the local filesystem storage backend.

        Args:
            base_path: Root directory under which bucket subdirectories are created.
        """
        self._base = base_path

    def upload(self, bucket: str, key: str, data: bytes) -> None:
        """Write bytes to the local filesystem under base_path/bucket/key.

        Args:
            bucket: Subdirectory acting as the bucket.
            key: Relative file path within the bucket directory.
            data: Raw bytes to write.
        """
        path = self._base / bucket / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def download(self, bucket: str, key: str) -> bytes:
        """Read and return bytes from base_path/bucket/key.

        Args:
            bucket: Subdirectory acting as the bucket.
            key: Relative file path within the bucket directory.

        Returns:
            File content as bytes.
        """
        path = self._base / bucket / key
        return path.read_bytes()

    def exists(self, bucket: str, key: str) -> bool:
        """Return True if the file at base_path/bucket/key exists.

        Args:
            bucket: Subdirectory acting as the bucket.
            key: Relative file path within the bucket directory.

        Returns:
            True if the file exists, False otherwise.
        """
        return (self._base / bucket / key).exists()

    def delete(self, bucket: str, key: str) -> None:
        """Delete the file at base_path/bucket/key if it exists.

        Args:
            bucket: Subdirectory acting as the bucket.
            key: Relative file path within the bucket directory.
        """
        path = self._base / bucket / key
        if path.exists():
            path.unlink()

    def ensure_buckets(self) -> None:
        """No-op for local storage; present for protocol compatibility."""
        # Not strictly needed for local, but for protocol compatibility
        pass
