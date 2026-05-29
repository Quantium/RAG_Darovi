"""Minimal HTTP surface for on-demand extract_text runs."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

_app_state: dict[str, Any] = {}


def configure_http_api(*, service: Any, settings: Any) -> None:
    """Inject the ExtractTextService and Settings into the HTTP API's global state.

    Must be called before the first request is handled.

    Args:
        service: An ExtractTextService instance to use for on-demand runs.
        settings: Application settings (stored for potential future route use).
    """
    _app_state["service"] = service
    _app_state["settings"] = settings
    _app_state["last_result"] = None
    _app_state["last_error"] = None


app = FastAPI(title="extract-text triggers", version="1.0.0")


class TriggerAccepted(BaseModel):
    accepted: bool
    result: dict[str, int] | None = None
    error: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    """Return a simple liveness check payload."""
    return {"status": "ok"}


@app.get("/trigger/state")
def trigger_state() -> dict[str, Any]:
    """Return the service readiness state and results of the last extraction run."""
    return {
        "service_ready": _app_state.get("service") is not None,
        "last_run": _app_state.get("last_result"),
        "last_error": _app_state.get("last_error"),
    }


@app.post("/trigger/run", response_model=TriggerAccepted)
def trigger_run() -> TriggerAccepted:
    """Trigger an on-demand extraction run and return the result synchronously.

    Returns:
        TriggerAccepted indicating success or failure, with scanned/updated/failed counts on success.
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
