#!/usr/bin/env python3
"""One-off migration: load milvus_vectors.parquet into a Zilliz Cloud cluster.

Usage:
    export MILVUS_URI=https://in03-xxx.zillizcloud.com:443
    export MILVUS_TOKEN=<your_api_key>
    uv run scripts/migrate_to_zilliz.py [path/to/milvus_vectors.parquet]

If no path is given, the script looks for the most recent backup automatically.
"""
import os
import sys
import glob

import pandas as pd
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

# ── Configuration ──────────────────────────────────────────────────────────────
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION", "rag_documents")
MILVUS_URI = os.getenv("MILVUS_URI", "")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
EMBED_DIM = int(os.getenv("EMBED_DIM", "3072"))
BATCH_SIZE = 1000
VALID_PARTITIONS = {"doc", "sheet", "pdf"}


def resolve_parquet(path_arg: str | None) -> str:
    if path_arg:
        return path_arg
    candidates = sorted(glob.glob("backups/*/milvus_vectors.parquet"))
    if not candidates:
        print("ERROR: no milvus_vectors.parquet found under backups/", file=sys.stderr)
        sys.exit(1)
    latest = candidates[-1]
    print(f"Auto-selected backup: {latest}")
    return latest


def connect_zilliz() -> None:
    if not MILVUS_URI:
        print("ERROR: MILVUS_URI is not set. Export it before running.", file=sys.stderr)
        sys.exit(1)
    print(f"Connecting to Zilliz: {MILVUS_URI}")
    connections.connect(uri=MILVUS_URI, token=MILVUS_TOKEN)


def create_collection() -> Collection:
    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=256, is_primary=True),
        FieldSchema(name="source_file_id", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="source_name", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="document_type", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="section_title", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="chunk_index", dtype=DataType.INT64),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBED_DIM),
    ]
    schema = CollectionSchema(fields, description="RAG Darovi Documents")
    col = Collection(COLLECTION_NAME, schema)

    col.create_index(
        field_name="embedding",
        index_params={
            "metric_type": "COSINE",
            "index_type": "HNSW",
            "params": {"M": 16, "efConstruction": 256},
        },
    )

    for part in VALID_PARTITIONS:
        col.create_partition(part)

    col.load()
    print(f"Created collection '{COLLECTION_NAME}' with HNSW index and partitions.")
    return col


def insert_batch(col: Collection, rows: list[dict], partition: str) -> None:
    data = [
        [r["id"] for r in rows],
        [r["source_file_id"] for r in rows],
        [r["source_name"] for r in rows],
        [r["document_type"] for r in rows],
        [r["section_title"] for r in rows],
        [int(r["chunk_index"]) for r in rows],
        [r["text"] for r in rows],
        [r["embedding"] for r in rows],
    ]
    col.insert(data, partition_name=partition)


def main() -> None:
    parquet_path = resolve_parquet(sys.argv[1] if len(sys.argv) > 1 else None)

    connect_zilliz()

    if utility.has_collection(COLLECTION_NAME):
        existing = Collection(COLLECTION_NAME)
        existing.load()
        count = existing.num_entities
        print(f"Collection '{COLLECTION_NAME}' already exists with {count:,} entities.")
        answer = input("Drop and re-create it? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)
        utility.drop_collection(COLLECTION_NAME)
        print("Dropped existing collection.")

    col = create_collection()

    print(f"Reading {parquet_path} …")
    df = pd.read_parquet(parquet_path, engine="pyarrow")
    total = len(df)
    print(f"Loaded {total:,} rows from parquet.")

    # Fill missing metadata fields with safe defaults
    df["source_file_id"] = df["source_file_id"].fillna("").astype(str)
    df["source_name"] = df["source_name"].fillna("").astype(str)
    df["document_type"] = df["document_type"].fillna("doc").astype(str)
    df["section_title"] = df["section_title"].fillna("").astype(str)
    df["text"] = df["text"].fillna("").astype(str)
    df["chunk_index"] = df["chunk_index"].fillna(0).astype(int)

    inserted = 0
    for doc_type, group in df.groupby("document_type"):
        partition = doc_type.lower() if doc_type.lower() in VALID_PARTITIONS else "doc"
        rows = group.to_dict("records")
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            insert_batch(col, batch, partition)
            inserted += len(batch)
            pct = 100 * inserted // max(total, 1)
            print(f"  {inserted:,} / {total:,}  ({pct}%)", end="\r", flush=True)

    col.flush()
    print(f"\nDone. Inserted {inserted:,} vectors into '{COLLECTION_NAME}' on Zilliz.")
    col.load()
    print(f"Entity count (from cluster): {col.num_entities:,}")


if __name__ == "__main__":
    main()
