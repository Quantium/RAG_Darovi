"""HTTP trigger surface for extract_text."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.http_api import app, configure_http_api


def test_health_endpoint() -> None:
    """Verify that GET /health returns HTTP 200 with status 'ok'."""
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}


def test_trigger_run_invokes_service() -> None:
    """Verify that POST /trigger/run calls service.run_once and returns accepted=True."""
    svc = MagicMock()
    svc.run_once.return_value = {"processed": 3}
    configure_http_api(service=svc, settings=MagicMock())
    client = TestClient(app)
    r = client.post("/trigger/run")
    assert r.status_code == 200
    assert r.json()["accepted"] is True
    svc.run_once.assert_called_once()
