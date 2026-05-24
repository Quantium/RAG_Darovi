from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from pymilvus import Collection, connections

from .settings import Settings


@dataclass
class RetrievedChunk:
    text: str
    source_file_id: str
    source_name: str
    section_title: str
    chunk_index: int
    score: float


def _extract_keywords(query: str) -> list[str]:
    """Extract tokens worth keyword-searching: proper nouns, codes, numbers ≥5 chars."""
    tokens: list[str] = []
    # Alphanumeric codes (registration numbers, solicitud numbers)
    tokens += re.findall(r'[A-Z0-9]{5,}', query)
    # Capitalized multi-char words (product/company names)
    tokens += [w for w in re.findall(r'[A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ]{3,}', query)
               if w.lower() not in {'registro', 'sanitario', 'medicamento', 'producto',
                                    'titular', 'solicitud', 'cuantos', 'dame', 'lista',
                                    'todos', 'tiene', 'cual', 'que', 'como', 'hay'}]
    # Keep unique, max 4 tokens
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            result.append(t)
        if len(result) >= 4:
            break
    return result


class Retriever:
    def __init__(self, settings: Settings, cache: Any | None = None) -> None:
        self._settings = settings
        self._cache = cache
        self._cache_ttl = 3600
        connections.connect(host=settings.milvus_host, port=settings.milvus_port)

    async def retrieve(self, query: str, top_k: int = 10, document_type: str | None = None) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        cache_key = None
        if self._cache is not None:
            raw_key = f"ra-retrieval-v2:{self._settings.embed_model}:{query}:{top_k}:{document_type}"
            cache_key = hashlib.sha256(raw_key.encode()).hexdigest()
            cached = self._cache.get(cache_key)
            if cached:
                payload = json.loads(cached)
                return [RetrievedChunk(**item) for item in payload]

        collection = Collection(self._settings.milvus_collection)
        partition_names = [document_type] if document_type else None

        # --- Vector search ---
        embedding = await self._embed_query(query)
        search_params = {"metric_type": "COSINE", "params": {"ef": 128}}
        hits = collection.search(
            [embedding],
            "embedding",
            search_params,
            limit=top_k,
            partition_names=partition_names,
            output_fields=["source_file_id", "source_name", "section_title", "chunk_index", "text"],
        )
        seen: set[str] = set()
        result: list[RetrievedChunk] = []
        for group in hits:
            for hit in group:
                key = f"{hit.entity.get('source_file_id')}:{hit.entity.get('chunk_index')}"
                seen.add(key)
                result.append(
                    RetrievedChunk(
                        text=hit.entity.get("text"),
                        source_file_id=hit.entity.get("source_file_id"),
                        source_name=hit.entity.get("source_name"),
                        section_title=hit.entity.get("section_title"),
                        chunk_index=hit.entity.get("chunk_index") or 0,
                        score=float(hit.score),
                    )
                )

        # --- Keyword fallback for proper nouns and codes ---
        keywords = _extract_keywords(query)
        # Try each keyword in original case and uppercase (OCR often produces uppercase text)
        kw_variants: list[str] = []
        for kw in keywords:
            kw_safe = kw.replace('"', '').replace("'", "")
            kw_variants.append(kw_safe)
            upper = kw_safe.upper()
            if upper != kw_safe:
                kw_variants.append(upper)

        for kw_safe in kw_variants:
            try:
                expr = f'text like "%{kw_safe}%"'
                kw_hits = collection.query(
                    expr=expr,
                    output_fields=["source_file_id", "source_name", "section_title", "chunk_index", "text"],
                    limit=5,
                )
                for hit in kw_hits:
                    key = f"{hit['source_file_id']}:{hit['chunk_index']}"
                    if key not in seen:
                        seen.add(key)
                        result.append(
                            RetrievedChunk(
                                text=hit["text"],
                                source_file_id=hit["source_file_id"],
                                source_name=hit["source_name"],
                                section_title=hit["section_title"],
                                chunk_index=hit.get("chunk_index") or 0,
                                score=0.80,  # fixed score for keyword hits
                            )
                        )
            except Exception:
                pass

        # Sort by score descending, keep top_k * 2 to give LLM more context
        result.sort(key=lambda c: c.score, reverse=True)
        result = result[: top_k * 2]

        if self._cache is not None and cache_key is not None:
            self._cache.set(
                cache_key,
                json.dumps([chunk.__dict__ for chunk in result]),
                ex=self._cache_ttl,
            )
        return result

    async def _embed_query(self, query: str) -> list[float]:
        headers = {"Authorization": f"Bearer {self._settings.embed_api_key.get_secret_value()}"}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._settings.embed_api_url.rstrip('/')}/embeddings",
                json={"model": self._settings.embed_model, "input": [query]},
                headers=headers,
            )
            response.raise_for_status()
            return response.json()["data"][0]["embedding"]
