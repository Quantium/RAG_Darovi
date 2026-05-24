from __future__ import annotations

import httpx

from .schemas import RetrieveResponse
from .settings import Settings


class RetrievalClient:
    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.retrieval_admin_base_url.rstrip("/")

    async def retrieve(self, *, query: str, top_k: int = 10, document_type: str | None = None, api_key: str | None = None) -> RetrieveResponse:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        payload = {"query": query, "top_k": top_k, "document_type": document_type}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self._base_url}/retrieve", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return RetrieveResponse(**data)
