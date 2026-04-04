from __future__ import annotations

from typing import Callable

from config.settings import Settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.storage.backend import MinIOStorage
from src.metadata.repository import SyncMetadataRepository


def build_settings() -> Settings:
    return Settings()


def build_storage(settings: Settings | None = None) -> MinIOStorage:
    s = settings or build_settings()
    return MinIOStorage(s)


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
}


def derive_document_type(mime_type: str) -> str:
    return MIME_TO_DOC_TYPE.get(mime_type, "doc")
