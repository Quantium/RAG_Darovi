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
        """Initialize the Milvus store, connecting to the configured host and port.

        Args:
            settings: Application settings providing collection name, embedding dim, and host/port.
            client: Optional mock client injected during tests (skips live Milvus connection).
        """
        self._collection_name = settings.milvus_collection
        self._dim = settings.embed_dim
        self._host = settings.milvus_host
        self._port = settings.milvus_port
        self._uri = settings.milvus_uri
        self._token = settings.milvus_token
        self._client = client  # injected mock for tests

        if client is None:
            if self._uri:
                connections.connect(uri=self._uri, token=self._token)
            else:
                connections.connect(host=self._host, port=self._port)

    def collection_exists(self) -> bool:
        """Return True if the configured Milvus collection already exists.

        Returns:
            True if the collection is present, False otherwise.
        """
        if self._client:
            return self._client.has_collection(self._collection_name)
        return utility.has_collection(self._collection_name)

    def create_collection(self) -> None:
        """Create the Milvus collection with schema, HNSW index, and default partitions.

        Partitions created: 'doc', 'sheet', 'pdf'.
        """
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
        """Create the Milvus collection if it does not already exist."""
        if not self.collection_exists():
            self.create_collection()

    def drop_collection_if_exists(self) -> None:
        """Remove the entire vector collection (all partitions and data). Used when switching Drive folder."""
        if self._client:
            if self._client.has_collection(self._collection_name):
                self._client.drop_collection(self._collection_name)
        else:
            if utility.has_collection(self._collection_name):
                utility.drop_collection(self._collection_name)
        logger.info("milvus.collection_dropped", name=self._collection_name)

    def count_entities(self) -> int:
        """Return total vector rows in the collection, or 0 if missing / empty."""
        if not self.collection_exists():
            return 0
        if self._client:
            fn = getattr(self._client, "num_entities", None)
            if callable(fn):
                return int(fn(self._collection_name))
            return 0
        col = Collection(self._collection_name)
        col.load()
        return int(col.num_entities)

    def delete_all_vectors(self) -> None:
        """Drop the collection entirely (same as selective folder wipe)."""
        self.drop_collection_if_exists()

    def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        """Insert chunk metadata and their embeddings into the appropriate Milvus partition.

        Batches inserts in groups of MILVUS_INSERT_BATCH_SIZE. The partition is derived
        from the 'document_type' field of the first chunk; unknown types default to 'doc'.

        Args:
            chunks: List of chunk dicts with 'id', 'source_file_id', 'text', etc.
            embeddings: Parallel list of embedding vectors, one per chunk.
        """
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
        """Perform a COSINE similarity search and return the top-k results.

        Args:
            query_embedding: Dense vector to search against.
            top_k: Maximum number of nearest neighbors to return.
            partition: Optional partition name to restrict the search scope.

        Returns:
            List of dicts with 'id', 'source_file_id', 'source_name', 'section_title',
            'text', and 'score' for each result.
        """
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
        """Delete all Milvus vectors associated with a given source file ID.

        Args:
            source_file_id: Source file identifier whose vectors should be removed.
        """
        expr = f'source_file_id == "{source_file_id}"'
        if self._client:
            self._client.delete(self._collection_name, expr)
        else:
            col = Collection(self._collection_name)
            col.delete(expr)

        logger.info("milvus.deleted_source", source_file_id=source_file_id)
