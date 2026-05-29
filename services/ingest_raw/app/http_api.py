"""Minimal HTTP surface for on-demand ingest runs (dashboard trigger)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

_app_state: dict[str, Any] = {}


def configure_http_api(*, service: Any, settings: Any) -> None:
    """Inject the IngestRawService and Settings into the HTTP API's global state.

    Must be called before the first request is handled.

    Args:
        service: An IngestRawService instance to use for on-demand runs.
        settings: Application settings (stored for use in source-count and other routes).
    """
    _app_state["service"] = service
    _app_state["settings"] = settings
    _app_state["last_result"] = None
    _app_state["last_error"] = None


app = FastAPI(title="ingest-raw triggers", version="1.0.0")


class TriggerAccepted(BaseModel):
    accepted: bool
    result: dict[str, int] | None = None
    error: str | None = None


class SourceCountResponse(BaseModel):
    count: int
    source_url: str


@app.get("/health")
def health() -> dict[str, str]:
    """Return a simple liveness check payload."""
    return {"status": "ok"}


@app.get("/trigger/state")
def trigger_state() -> dict[str, Any]:
    """Return the service readiness state and results of the last ingestion run."""
    return {
        "service_ready": _app_state.get("service") is not None,
        "last_run": _app_state.get("last_result"),
        "last_error": _app_state.get("last_error"),
    }


@app.get("/trigger/source-count", response_model=SourceCountResponse)
def trigger_source_count() -> SourceCountResponse:
    """Count the total number of files in the configured source and return the source URL.

    Returns:
        SourceCountResponse with the file count and a human-readable source URL.
    """
    settings = _app_state.get("settings")
    if settings is None:
        return SourceCountResponse(count=0, source_url="")
    from app.sources import build_source_adapter

    source = build_source_adapter(settings)
    files = source.list_files()
    if settings.ingest_source == "local":
        from pathlib import Path
        from urllib.parse import quote

        root = Path(settings.local_source_folder or "").expanduser()
        url = root.as_uri() if root.exists() else f"file://{quote(str(root))}"
    else:
        folder = (settings.drive_folder_id or "").strip()
        url = f"https://drive.google.com/drive/folders/{folder}" if folder else "https://drive.google.com"
    return SourceCountResponse(count=len(files), source_url=url)


@app.post("/trigger/run", response_model=TriggerAccepted)
def trigger_run() -> TriggerAccepted:
    """Trigger an on-demand ingestion run and return the result synchronously.

    Returns:
        TriggerAccepted indicating success or failure, with scanned/updated/skipped counts on success.
    """
    svc = _app_state.get("service")
    if svc is None:
        return TriggerAccepted(accepted=False, error="service not configured")
    try:
        result = svc.run_once()
        _app_state["last_result"] = result
        _app_state["last_error"] = None
        return TriggerAccepted(accepted=True, result=result)
    except Exception as exc:
        _app_state["last_error"] = str(exc)
        return TriggerAccepted(accepted=False, error=str(exc))
