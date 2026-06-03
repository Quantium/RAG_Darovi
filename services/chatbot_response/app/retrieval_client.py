from __future__ import annotations

import httpx

from .schemas import RetrieveResponse
from .settings import Settings


class RetrievalClient:
    def __init__(self, settings: Settings) -> None:
        """Initialize the HTTP client wrapper for the retrieval-admin service.

        Args:
            settings: Application settings providing the retrieval service base URL.
        """
        self._base_url = settings.retrieval_admin_base_url.rstrip("/")

    async def retrieve(
        self,
        *,
        query: str,
        top_k: int = 10,
        document_type: str | None = None,
        licitacion: str | None = None,
        api_key: str | None = None,
    ) -> RetrieveResponse:
        """Send a retrieval request to the retrieval-admin service and return ranked results.

        Args:
            query: Natural-language query to embed and search.
            top_k: Maximum number of results to return.
            document_type: Optional filter to restrict results to a specific document category.
            licitacion: Licitación slug; retrieval-admin resolves it to that tenant's collection.
            api_key: Optional X-API-Key header value to forward to the downstream service.

        Returns:
            RetrieveResponse containing the query, assembled context text, and source references.

        Raises:
            httpx.HTTPStatusError: If the retrieval service returns a non-2xx response.
        """
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        payload = {"query": query, "top_k": top_k, "document_type": document_type}
        if licitacion:
            payload["licitacion"] = licitacion
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self._base_url}/retrieve", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return RetrieveResponse(**data)
