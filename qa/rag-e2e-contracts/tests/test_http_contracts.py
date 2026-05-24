from __future__ import annotations

import os

import httpx


RETRIEVAL_ADMIN_BASE_URL = os.getenv("RETRIEVAL_ADMIN_BASE_URL", "http://localhost:8010").rstrip("/")
CHATBOT_RESPONSE_BASE_URL = os.getenv("CHATBOT_RESPONSE_BASE_URL", "http://localhost:8020").rstrip("/")


def test_retrieval_admin_health() -> None:
    response = httpx.get(f"{RETRIEVAL_ADMIN_BASE_URL}/health", timeout=10.0)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chatbot_response_health() -> None:
    response = httpx.get(f"{CHATBOT_RESPONSE_BASE_URL}/health", timeout=10.0)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
