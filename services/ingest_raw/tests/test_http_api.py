"""HTTP trigger surface for ingest_raw."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.http_api import app, configure_http_api


def test_health_endpoint() -> None:
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}


def test_trigger_run_invokes_service() -> None:
    svc = MagicMock()
    svc.run_once.return_value = {"scanned": 2, "updated": 1, "skipped": 0}
    configure_http_api(service=svc, settings=MagicMock())
    client = TestClient(app)
    r = client.post("/trigger/run")
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert body["result"]["scanned"] == 2
    svc.run_once.assert_called_once()
