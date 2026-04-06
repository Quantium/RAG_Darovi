from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
import structlog

from config.settings import Settings

logger = structlog.get_logger()


class BatchEmbedder:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = settings.ollama_base_url
        self._model = settings.embed_model
        self._batch_size = settings.embed_batch_size
        self._dim = settings.embed_dim
        self._client = client

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
                logger.info(
                    "embedding.batch",
                    batch=f"{batch_num}/{total_batches}",
                    size=len(batch),
                )

                embeddings = await self._embed_batch(client, batch)
                all_embeddings.extend(embeddings)

        return all_embeddings

    @asynccontextmanager
    async def _get_client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        if self._client:
            yield self._client
        else:
            async with httpx.AsyncClient(timeout=60.0) as client:
                yield client

    async def _embed_batch(
        self, client: httpx.AsyncClient, texts: list[str], max_retries: int = 3
    ) -> list[list[float]]:
        for attempt in range(max_retries):
            try:
                # Identify empty texts
                empty_indices = [i for i, t in enumerate(texts) if not t.strip()]
                non_empty_texts = [t for t in texts if t.strip()]

                if empty_indices:
                    logger.warning(
                        "embedding.empty_texts",
                        count=len(empty_indices),
                        indices=empty_indices[:5],  # log first 5
                    )

                # If all texts are empty, return zero vectors
                if not non_empty_texts:
                    return [[0.0] * self._dim for _ in texts]

                response = await client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": non_empty_texts},
                )
                response.raise_for_status()
                embeddings = response.json()["embeddings"]

                # Validation: Ollama should return same number of embeddings as non-empty inputs
                if len(embeddings) != len(non_empty_texts):
                    logger.error(
                        "embedding.mismatch",
                        expected=len(non_empty_texts),
                        received=len(embeddings),
                    )
                    # Fill missing with zero vectors if necessary
                    while len(embeddings) < len(non_empty_texts):
                        embeddings.append([0.0] * self._dim)

                # Reconstruct full list with zero vectors for empty texts
                full_embeddings: list[list[float]] = []
                non_empty_idx = 0
                for i in range(len(texts)):
                    if i in empty_indices:
                        full_embeddings.append([0.0] * self._dim)
                    else:
                        full_embeddings.append(embeddings[non_empty_idx])
                        non_empty_idx += 1

                return full_embeddings
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.HTTPStatusError) as exc:
                if attempt == max_retries - 1:
                    logger.error("embedding.failed", error=str(exc))
                    raise

                wait = 2**attempt
                logger.warning(
                    "embedding.retry",
                    attempt=attempt + 1,
                    wait=wait,
                    error=str(exc),
                )
                await asyncio.sleep(wait)

        # Unreachable but satisfies type checker
        return [[0.0] * self._dim for _ in texts]
