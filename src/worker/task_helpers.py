from __future__ import annotations

from typing import Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from config.settings import Settings
from src.metadata.repository import SyncMetadataRepository
from src.storage.backend import MinIOStorage


def build_settings() -> Settings:
    return Settings()


def build_storage(settings: Settings | None = None) -> MinIOStorage:
    s = settings or build_settings()
    return MinIOStorage(s)


def build_metadata_repo(settings: Settings | None = None) -> tuple[SyncMetadataRepository, Callable[[], None]]:
    """Return (repo, cleanup_fn). Caller must call cleanup_fn() when done.

    Uses synchronous engine — safe to use in Celery tasks without
    event loop issues.
    """
    s = settings or build_settings()
    # Note: Using database_url_sync which should use a sync driver like psycopg2 or sqlite (sync)
    engine = create_engine(s.database_url_sync.get_secret_value())
    session = Session(engine)
    repo = SyncMetadataRepository(session)

    def cleanup() -> None:
        session.close()
        engine.dispose()

    return repo, cleanup


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
