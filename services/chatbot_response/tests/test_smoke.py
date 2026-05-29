from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import create_app


def test_health() -> None:
    """Smoke test: verify the chatbot service health endpoint responds with HTTP 200."""
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
