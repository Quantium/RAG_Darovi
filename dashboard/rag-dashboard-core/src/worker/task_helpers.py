from __future__ import annotations

from typing import Callable

from config.settings import Settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.storage.backend import MinIOStorage
from src.metadata.repository import SyncMetadataRepository


def build_settings() -> Settings:
    """Instantiate and return a fresh Settings object from environment variables.

    Returns:
        Populated Settings instance.
    """
    return Settings()


def build_storage(settings: Settings | None = None) -> MinIOStorage:
    """Build and return a MinIOStorage with buckets ensured to exist.

    Args:
        settings: Optional settings; defaults to a fresh Settings() if not provided.

    Returns:
        Ready-to-use MinIOStorage instance.
    """
    s = settings or build_settings()
    storage = MinIOStorage(s)
    storage.ensure_buckets()
    return storage


def build_metadata_repo(settings: Settings | None = None) -> tuple[SyncMetadataRepository, Callable[[], None]]:
    """Return (repo, cleanup_fn). Caller must call cleanup_fn() when done.

    Uses synchronous psycopg2 engine — safe to use in Celery tasks without
    event loop issues.
    """
    s = settings or build_settings()
    engine = create_engine(s.database_url_sync.get_secret_value())
    session = Session(engine)
    repo = SyncMetadataRepository(session)

    def cleanup() -> None:
        """Close the database session and dispose of the engine connection pool."""
        session.close()
        engine.dispose()

    return repo, cleanup


def build_tenant_metadata_repo(
    settings: Settings, schema_name: str
) -> tuple[SyncMetadataRepository, Callable[[], None]]:
    """Return (repo, cleanup) bound to the licitación ``schema_name``.

    Same contract as :func:`build_metadata_repo`, but every bare-table query resolves
    inside the tenant schema because the engine pins ``search_path`` at the connection
    level. ``schema_name='public'`` yields the legacy single-tenant behavior.
    """
    from src.tenant.engine import build_tenant_engine

    engine = build_tenant_engine(settings, schema_name)
    session = Session(engine)
    repo = SyncMetadataRepository(session)

    def cleanup() -> None:
        """Close the database session and dispose of the engine connection pool."""
        session.close()
        engine.dispose()

    return repo, cleanup


def ensure_milvus_collection(settings: Settings | None = None) -> None:
    """Create the Milvus collection if it doesn't exist. Idempotent."""
    from src.vectorizer.milvus_store import MilvusStore

    s = settings or build_settings()
    store = MilvusStore(s)
    store.ensure_collection()


MIME_TO_DOC_TYPE: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.google-apps.document": "doc",
    "application/vnd.google-apps.spreadsheet": "sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/plain": "doc",
    "text/markdown": "doc",
    "text/html": "html",
    "text/csv": "sheet",
    "image/png": "image",
    "image/jpeg": "image",
    "image/jpg": "image",
    "image/tiff": "image",
    "image/webp": "image",
}


def derive_document_type(mime_type: str) -> str:
    """Map a MIME type string to a document type identifier used by the vector store.

    Args:
        mime_type: MIME type string to classify.

    Returns:
        Document type string (e.g. 'pdf', 'doc', 'sheet'); defaults to 'doc' for unknown types.
    """
    return MIME_TO_DOC_TYPE.get(mime_type, "doc")
