from __future__ import annotations

import structlog
import threading

import uvicorn

from app.cron_runner import run_forever
from app.db import create_repository
from app.http_api import app as http_app, configure_http_api
from app.service import IngestRawService
from app.settings import Settings
from app.sources import build_source_adapter
from app.storage import MinIOStorage

logger = structlog.get_logger()


def main() -> None:
    """Bootstrap and run the Ingest Raw service.

    Wires up all dependencies, optionally starts an HTTP trigger server in a daemon thread,
    optionally runs one ingestion pass on startup, and then enters the cron loop.
    """
    settings = Settings()
    repo = create_repository(settings)
    source = build_source_adapter(settings)
    storage = MinIOStorage(settings)
    service = IngestRawService(settings=settings, repo=repo, source=source, storage=storage)

    configure_http_api(service=service, settings=settings)
    if settings.ingest_raw_http_enabled:
        port = int(settings.ingest_raw_http_port)

        def _run_http() -> None:
            """Start the uvicorn server for the HTTP trigger API on the configured port."""
            uvicorn.run(http_app, host="0.0.0.0", port=port, log_level="warning")

        threading.Thread(target=_run_http, daemon=True).start()
        logger.info("ingest_raw.http.started", port=port)

    if settings.ingest_raw_run_on_start:
        logger.info("ingest_raw.bootstrap_run.start")
        service.run_once()

    run_forever(settings.ingest_raw_cron, service.run_once)


if __name__ == "__main__":
    main()
