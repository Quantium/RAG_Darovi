from __future__ import annotations

from typing import Any, Protocol

import structlog
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from config.settings import Settings

logger = structlog.get_logger()

MILVUS_INSERT_BATCH_SIZE = 1000


class VectorStore(Protocol):
    def create_collection(self) -> None: ...
    def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None: ...
    def search(self, query_embedding: list[float], top_k: int, partition: str | None = None) -> list[dict]: ...
    def delete_by_source(self, source_file_id: str) -> None: ...
    def collection_exists(self) -> bool: ...


class MilvusStore:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._collection_name = settings.milvus_collection
        self._dim = settings.embed_dim
        self._host = settings.milvus_host
        self._port = settings.milvus_port
        self._client = client  # injected mock for tests

        if client is None:
            connections.connect(host=self._host, port=self._port)

    def collection_exists(self) -> bool:
        if self._client:
            return self._client.has_collection(self._collection_name)
        return utility.has_collection(self._collection_name)

    def create_collection(self) -> None:
        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=256, is_primary=True),
            FieldSchema(name="source_file_id", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="source_name", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="document_type", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="section_title", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="chunk_index", dtype=DataType.INT64),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self._dim),
        ]
        schema = CollectionSchema(fields, description="RAG Darovi Documents")

        if self._client:
            self._client.create_collection(self._collection_name, schema)
        else:
            col = Collection(self._collection_name, schema)

            # Create HNSW index
            index_params = {
                "metric_type": "COSINE",
                "index_type": "HNSW",
                "params": {"M": 16, "efConstruction": 256},
            }
            col.create_index(field_name="embedding", index_params=index_params)

            # Create partitions
            for part in ["doc", "sheet", "pdf"]:
                col.create_partition(part)

            col.load()

        logger.info("milvus.collection_created", name=self._collection_name)

    def ensure_collection(self) -> None:
        if not self.collection_exists():
            self.create_collection()

    def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        if not chunks:
            return

        # Determine partition from document_type
        # Milvus partition name must be alphanumeric/underscore
        partition_name = chunks[0].get("document_type", "doc").lower()
        if partition_name not in ["doc", "sheet", "pdf"]:
            partition_name = "doc"

        # Milvus expects a list of columns
        data = [
            [c.get("id") for c in chunks],
            [c.get("source_file_id") for c in chunks],
            [c.get("source_name", "unknown") for c in chunks],
            [c.get("document_type", "doc") for c in chunks],
            [c.get("section_title", "") for c in chunks],
            [c.get("chunk_index", 0) for c in chunks],
            [c.get("text", "") for c in chunks],
            embeddings,
        ]

        if self._client:
            self._client.insert(self._collection_name, data, partition_name=partition_name)
        else:
            col = Collection(self._collection_name)

            # Batch inserts in groups of 1000
            for i in range(0, len(chunks), MILVUS_INSERT_BATCH_SIZE):
                batch_chunks_data = [col_data[i : i + MILVUS_INSERT_BATCH_SIZE] for col_data in data]
                col.insert(batch_chunks_data, partition_name=partition_name)

            col.flush()

        logger.info("milvus.upserted", count=len(chunks), partition=partition_name)

    def search(self, query_embedding: list[float], top_k: int = 10, partition: str | None = None) -> list[dict]:
        search_params = {"metric_type": "COSINE", "params": {"ef": 128}}
        partition_names = [partition] if partition else None

        if self._client:
            results = self._client.search(
                self._collection_name,
                [query_embedding],
                "embedding",
                search_params,
                limit=top_k,
                partition_names=partition_names,
                output_fields=["source_file_id", "source_name", "section_title", "text"],
            )
        else:
            col = Collection(self._collection_name)
            results = col.search(
                [query_embedding],
                "embedding",
                search_params,
                limit=top_k,
                partition_names=partition_names,
                output_fields=["source_file_id", "source_name", "section_title", "text"],
            )

        output = []
        for hits in results:
            for hit in hits:
                output.append(
                    {
                        "id": hit.id,
                        "source_file_id": hit.entity.get("source_file_id"),
                        "source_name": hit.entity.get("source_name"),
                        "section_title": hit.entity.get("section_title"),
                        "text": hit.entity.get("text"),
                        "score": hit.score,
                    }
                )
        return output

    def delete_by_source(self, source_file_id: str) -> None:
        expr = f'source_file_id == "{source_file_id}"'
        if self._client:
            self._client.delete(self._collection_name, expr)
        else:
            col = Collection(self._collection_name)
            col.delete(expr)

        logger.info("milvus.deleted_source", source_file_id=source_file_id)
