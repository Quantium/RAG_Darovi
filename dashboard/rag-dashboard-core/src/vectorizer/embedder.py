from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
import structlog

from config.settings import Settings

logger = structlog.get_logger()


class BatchEmbedder:
    """Batch text embedder using an OpenAI-compatible /v1/embeddings endpoint."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._batch_size = settings.embed_batch_size
        self._dim = settings.embed_dim
        self._timeout = float(settings.embed_request_timeout_s)
        self._client = client
        self._api_url = settings.embed_api_url.rstrip("/")
        self._api_key = settings.embed_api_key.get_secret_value()
        self._model = settings.embed_model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches. Returns one vector per input text."""
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        total_batches = (len(texts) + self._batch_size - 1) // self._batch_size

        async with self._get_client() as client:
            for i in range(0, len(texts), self._batch_size):
                batch = texts[i : i + self._batch_size]
                batch_num = i // self._batch_size + 1
                logger.info("embedding.batch", batch=f"{batch_num}/{total_batches}", size=len(batch))
                all_embeddings.extend(await self._embed_batch(client, batch))

        return all_embeddings

    @asynccontextmanager
    async def _get_client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        if self._client:
            yield self._client
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                yield client

    async def _embed_batch(self, client: httpx.AsyncClient, texts: list[str], max_retries: int = 3) -> list[list[float]]:
        empty_indices = {i for i, t in enumerate(texts) if not t.strip()}
        non_empty = [t for t in texts if t.strip()]

        if empty_indices:
            logger.warning("embedding.empty_texts", count=len(empty_indices))

        if not non_empty:
            return [[0.0] * self._dim for _ in texts]

        for attempt in range(max_retries):
            try:
                response = await client.post(
                    f"{self._api_url}/embeddings",
                    json={"model": self._model, "input": non_empty},
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                response.raise_for_status()
                data = response.json()["data"]
                data.sort(key=lambda x: x["index"])
                embeddings = [item["embedding"] for item in data]

                if len(embeddings) != len(non_empty):
                    logger.error("embedding.mismatch", expected=len(non_empty), received=len(embeddings))
                    while len(embeddings) < len(non_empty):
                        embeddings.append([0.0] * self._dim)

                full: list[list[float]] = []
                non_empty_idx = 0
                for i in range(len(texts)):
                    if i in empty_indices:
                        full.append([0.0] * self._dim)
                    else:
                        full.append(embeddings[non_empty_idx])
                        non_empty_idx += 1
                return full

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.HTTPStatusError) as exc:
                if attempt == max_retries - 1:
                    logger.error("embedding.failed", error=str(exc))
                    raise
                wait = 2**attempt
                logger.warning("embedding.retry", attempt=attempt + 1, wait=wait, error=str(exc))
                await asyncio.sleep(wait)

        return [[0.0] * self._dim for _ in texts]
