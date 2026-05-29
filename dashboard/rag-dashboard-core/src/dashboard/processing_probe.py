"""Best-effort detection of background pipeline activity (Celery + Postgres)."""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings

logger = structlog.get_logger()

_INGEST_NAMES = frozenset(
    {
        "src.worker.tasks.run_incremental_sync",
        "src.worker.tasks.restart_ingest",
        "src.worker.tasks.download_file",
    }
)
_VECTOR_NAMES = frozenset(
    {
        "src.worker.tasks.embed_file",
        "src.worker.tasks.vision_extract",
    }
)


class ProcessingProbe:
    def __init__(self, settings: Settings) -> None:
        """Initialize the probe with application settings.

        Args:
            settings: Application settings providing lock ID and other config.
        """
        self._settings = settings

    def celery_flags(self) -> tuple[bool, bool, dict | None]:
        """Return (ingest_busy, vectorize_busy, active_embed_args).

        active_embed_args is the args dict of the currently running embed_file task,
        containing drive_file_id, name, minio_text_key, etc. — or None if not running.
        """
        try:
            from src.worker.celery_app import app as celery_app

            inspect = celery_app.control.inspect(timeout=1.0)
            if not inspect:
                return False, False, None
            active = inspect.active() or {}
            ingest = False
            vector = False
            embed_args: dict | None = None
            for _worker, tasks in active.items():
                for t in tasks or []:
                    name = (t or {}).get("name") or ""
                    if name in _INGEST_NAMES:
                        ingest = True
                    if name in _VECTOR_NAMES or "embed" in name:
                        vector = True
                    if name == "src.worker.tasks.embed_file" and embed_args is None:
                        args = t.get("args") or []
                        if args and isinstance(args[0], dict):
                            embed_args = args[0]
            return ingest, vector, embed_args
        except Exception as exc:
            logger.warning("dashboard.celery_inspect_failed", error=str(exc))
            return False, False, None

    async def max_raw_synced_recent(self, session: AsyncSession, seconds: int = 120) -> bool:
        """Heuristic: raw ingest touched rows in the last `seconds` (Postgres)."""
        try:
            result = await session.execute(
                text(
                    """
                    SELECT EXISTS (
                      SELECT 1 FROM file_records
                      WHERE raw_synced_at IS NOT NULL
                        AND raw_synced_at > NOW() - (INTERVAL '1 second' * :sec)
                    )
                    """
                ),
                {"sec": seconds},
            )
            return bool(result.scalar())
        except Exception as exc:
            logger.warning("dashboard.recent_raw_query_failed", error=str(exc))
            return False

    async def advisory_extract_lock_held(self, session: AsyncSession) -> bool:
        """Check whether the extract_text advisory lock is currently held in PostgreSQL.

        Returns False for non-PostgreSQL backends (e.g., SQLite in tests).

        Args:
            session: Active SQLAlchemy async session.

        Returns:
            True if the lock is held by another session, False otherwise.
        """
        try:
            lock_id = int(self._settings.extract_text_lock_id)
            result = await session.execute(
                text(
                    """
                    SELECT EXISTS (
                      SELECT 1 FROM pg_locks
                      WHERE locktype = 'advisory'
                        AND ((classid::bigint << 32) | objid::bigint) = :lock_id
                    )
                    """
                ),
                {"lock_id": lock_id},
            )
            return bool(result.scalar())
        except Exception:
            # e.g. SQLite test DB — no pg_locks
            return False
