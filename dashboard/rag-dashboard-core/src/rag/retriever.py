from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

import structlog

from src.vectorizer.embedder import BatchEmbedder
from src.vectorizer.milvus_store import MilvusStore

logger = structlog.get_logger()


@dataclass
class RetrievedChunk:
    text: str
    source_file_id: str
    source_name: str
    section_title: str
    chunk_index: int
    score: float


class Retriever:
    def __init__(
        self,
        embedder: BatchEmbedder,
        vector_store: MilvusStore,
        cache: Any | None = None,
    ) -> None:
        """Initialize the retriever with an embedder, vector store, and optional Redis cache.

        Args:
            embedder: BatchEmbedder used to convert queries to dense vectors.
            vector_store: MilvusStore used to search for nearest-neighbor chunks.
            cache: Optional Redis client for caching retrieval results.
        """
        self._embedder = embedder
        self._vector_store = vector_store
        self._cache = cache  # Redis client
        self._cache_ttl = 3600  # 1 hour

    async def retrieve(
        self,
        query: str,
        top_k: int = 10,
        document_type: str | None = None,
    ) -> list[RetrievedChunk]:
        """Embed the query, search Milvus, and return ranked chunks with Redis caching.

        Args:
            query: Natural-language query to embed and search.
            top_k: Maximum number of results to retrieve from Milvus.
            document_type: Optional partition name to restrict the search scope.

        Returns:
            List of RetrievedChunk instances ordered by relevance score.
        """
        if not query.strip():
            return []

        # Build cache key
        cache_key_content = f"{query}:{top_k}:{document_type}"
        cache_key = f"retrieval:{hashlib.sha256(cache_key_content.encode()).hexdigest()}"

        # Check cache
        if self._cache:
            try:
                cached = self._cache.get(cache_key)
                if cached:
                    logger.info("retriever.cache_hit", query=query[:50])
                    data = json.loads(cached)
                    return [RetrievedChunk(**item) for item in data]
            except Exception as exc:
                logger.warning("retriever.cache_error", error=str(exc))

        # Embed query
        embeddings = await self._embedder.embed_texts([query])
        if not embeddings:
            return []
        query_vector = embeddings[0]

        # Search Milvus
        results = self._vector_store.search(query_vector, top_k, partition=document_type)

        # Map results - use .get() for robustness against varying mock structures in tests
        chunks = [
            RetrievedChunk(
                text=r.get("text", ""),
                source_file_id=r.get("source_file_id", "unknown"),
                source_name=r.get("source_name", "unknown"),
                section_title=r.get("section_title", "unknown"),
                chunk_index=r.get("chunk_index", 0),
                score=r.get("score", 0.0),
            )
            for r in results
        ]

        # Cache results
        if self._cache:
            try:
                serialized = json.dumps([asdict(c) for c in chunks])
                self._cache.set(cache_key, serialized, ex=self._cache_ttl)
            except Exception as exc:
                logger.warning("retriever.cache_store_error", error=str(exc))

        logger.info("retriever.search", query_length=len(query), results=len(chunks))
        return chunks
