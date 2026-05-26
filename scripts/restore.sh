#!/usr/bin/env bash
# restore.sh — Restore from a backup created by backup.sh
#
# Usage:
#   ./scripts/restore.sh backups/YYYYMMDD_HHMMSS
#   ./scripts/restore.sh backups/YYYYMMDD_HHMMSS --only-postgres
#   ./scripts/restore.sh backups/YYYYMMDD_HHMMSS --only-minio
#   ./scripts/restore.sh backups/YYYYMMDD_HHMMSS --only-milvus
#
# What it restores (if the file is present in the backup directory):
#   postgres.sql.gz              → PostgreSQL (drops existing data first)
#   minio_converted_texts.tar.gz → MinIO converted-texts bucket
#   milvus_vectors.parquet       → Milvus collection (drops + recreates)
#   minio_raw_files.tar.gz       → MinIO raw-files bucket (if present)
#
# WARNING: This OVERWRITES existing data. Make sure the stack is healthy before
# running (postgres, minio, milvus, dashboard-api must be up).
set -euo pipefail

BACKUP_DIR="${1:-}"
DO_POSTGRES=true
DO_MINIO=true
DO_MILVUS=true

# Parse optional flags (everything after the backup dir)
[[ $# -gt 0 ]] && shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        --only-postgres)  DO_POSTGRES=true;  DO_MINIO=false;  DO_MILVUS=false; shift ;;
        --only-minio)     DO_POSTGRES=false; DO_MINIO=true;   DO_MILVUS=false; shift ;;
        --only-milvus)    DO_POSTGRES=false; DO_MINIO=false;  DO_MILVUS=true;  shift ;;
        --only-fans)      echo "oh! you, nasty"; exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$BACKUP_DIR" ]]; then
    echo "Usage: $0 <backup-dir> [--only-postgres|--only-minio|--only-milvus]"
    echo "Example: $0 ./backups/20260524_220000"
    exit 1
fi

if [[ ! -d "$BACKUP_DIR" ]]; then
    echo "ERROR: directory not found: $BACKUP_DIR"
    exit 1
fi

echo "=== RAG Darovi restore from $BACKUP_DIR ==="
echo ""
echo "This will OVERWRITE existing data in PostgreSQL, MinIO, and Milvus."
echo "Press Ctrl+C within 10 seconds to cancel..."
sleep 10

echo ""
echo "Starting restore..."
echo ""

# ── 1. PostgreSQL ─────────────────────────────────────────────────────────────
if [[ "$DO_POSTGRES" == "true" ]] && [[ -f "$BACKUP_DIR/postgres.sql.gz" ]]; then
    echo "[1] PostgreSQL restore..."
    # Terminate existing connections to allow DROP operations
    docker compose exec -T postgres psql -U postgres -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='rag_darovi' AND pid <> pg_backend_pid();" \
        2>/dev/null || true
    gunzip -c "$BACKUP_DIR/postgres.sql.gz" \
        | docker compose exec -T postgres psql -U postgres -d rag_darovi -q
    echo "  OK  PostgreSQL restored"
elif [[ "$DO_POSTGRES" == "false" ]]; then
    echo "[1] Skipping PostgreSQL  (--only-* flag active)"
else
    echo "  --  postgres.sql.gz not found, skipping"
fi

# ── 2. MinIO converted-texts ──────────────────────────────────────────────────
if [[ "$DO_MINIO" == "true" ]] && [[ -f "$BACKUP_DIR/minio_converted_texts.tar.gz" ]]; then
    echo ""
    echo "[2] MinIO converted-texts restore..."
    DASH=$(docker compose ps -q dashboard-api)
    docker cp "$BACKUP_DIR/minio_converted_texts.tar.gz" "$DASH:/tmp/cts-restore.tar.gz"
    docker compose exec -T dashboard-api python3 << 'PYEOF'
import tarfile, os, io
from minio import Minio

client = Minio("minio:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
bucket = "converted-texts"
count = 0
with tarfile.open("/tmp/cts-restore.tar.gz", "r:gz") as tf:
    for member in tf.getmembers():
        if not member.isfile():
            continue
        f = tf.extractfile(member)
        if f:
            data = f.read()
            client.put_object(bucket, member.name.lstrip("./"), io.BytesIO(data), len(data))
            count += 1
print(f"  Restored {count} objects to {bucket}")
PYEOF
    docker compose exec -T dashboard-api rm -f /tmp/cts-restore.tar.gz
    echo "  OK  converted-texts restored"
elif [[ "$DO_MINIO" == "false" ]]; then
    echo ""
    echo "[2] Skipping MinIO texts  (--only-* flag active)"
else
    echo ""
    echo "  --  minio_converted_texts.tar.gz not found, skipping"
fi

# ── 3. MinIO raw-files ────────────────────────────────────────────────────────
if [[ "$DO_MINIO" == "true" ]] && [[ -f "$BACKUP_DIR/minio_raw_files.tar.gz" ]]; then
    echo ""
    echo "[3] MinIO raw-files restore..."
    DASH=$(docker compose ps -q dashboard-api)
    docker cp "$BACKUP_DIR/minio_raw_files.tar.gz" "$DASH:/tmp/raw-restore.tar.gz"
    docker compose exec -T dashboard-api python3 << 'PYEOF'
import tarfile, io
from minio import Minio

client = Minio("minio:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
bucket = "raw-files"
count = 0
with tarfile.open("/tmp/raw-restore.tar.gz", "r:gz") as tf:
    for member in tf.getmembers():
        if not member.isfile():
            continue
        f = tf.extractfile(member)
        if f:
            data = f.read()
            client.put_object(bucket, member.name.lstrip("./"), io.BytesIO(data), len(data))
            count += 1
            if count % 50 == 0:
                print(f"  {count} files restored...", flush=True)
print(f"  Restored {count} objects to {bucket}")
PYEOF
    docker compose exec -T dashboard-api rm -f /tmp/raw-restore.tar.gz
    echo "  OK  raw-files restored"
else
    echo ""
    echo "  --  minio_raw_files.tar.gz not found, skipping"
fi

# ── 4. Milvus vectors ─────────────────────────────────────────────────────────
if [[ "$DO_MILVUS" == "true" ]] && [[ -f "$BACKUP_DIR/milvus_vectors.parquet" ]]; then
    echo ""
    echo "[4] Milvus vector restore from parquet..."

    DASHBOARD_CONTAINER=$(docker compose ps -q dashboard-api)
    docker cp "$BACKUP_DIR/milvus_vectors.parquet" \
        "$DASHBOARD_CONTAINER:/tmp/milvus_restore.parquet"

    docker compose exec -T dashboard-api python3 << 'PYEOF'
import sys
import warnings
warnings.filterwarnings("ignore")

from pymilvus import (
    connections, Collection, CollectionSchema, FieldSchema,
    DataType, utility,
)
import pandas as pd
import numpy as np

connections.connect(host="milvus", port="19530")

COL_NAME = "rag_documents"
DIM = 3072  # text-embedding-3-large

# Drop existing collection
if utility.has_collection(COL_NAME):
    utility.drop_collection(COL_NAME)
    print("  Dropped existing collection")

# Recreate schema — must match milvus_store.py exactly
fields = [
    FieldSchema(name="id",             dtype=DataType.VARCHAR, max_length=256, is_primary=True),
    FieldSchema(name="source_file_id", dtype=DataType.VARCHAR, max_length=256),
    FieldSchema(name="source_name",    dtype=DataType.VARCHAR, max_length=512),
    FieldSchema(name="document_type",  dtype=DataType.VARCHAR, max_length=64),
    FieldSchema(name="section_title",  dtype=DataType.VARCHAR, max_length=512),
    FieldSchema(name="chunk_index",    dtype=DataType.INT64),
    FieldSchema(name="text",           dtype=DataType.VARCHAR, max_length=65535),
    FieldSchema(name="embedding",      dtype=DataType.FLOAT_VECTOR, dim=DIM),
]
schema = CollectionSchema(fields, description="RAG Darovi Documents")
col = Collection(COL_NAME, schema)

col.create_index(
    field_name="embedding",
    index_params={"metric_type": "COSINE", "index_type": "HNSW",
                  "params": {"M": 16, "efConstruction": 256}},
)
for part in ["doc", "sheet", "pdf"]:
    col.create_partition(part)

col.load()
print(f"  Collection '{COL_NAME}' created (dim={DIM}, HNSW COSINE)")

# Load parquet
df = pd.read_parquet("/tmp/milvus_restore.parquet", engine="pyarrow")
total = len(df)
print(f"  {total:,} vectors to insert...", flush=True)

# Insert in batches, routing to the correct partition
BATCH = 3000
inserted = 0

for start in range(0, total, BATCH):
    batch_df = df.iloc[start : start + BATCH]

    # Partition routing by document_type
    for doc_type, grp in batch_df.groupby("document_type"):
        partition = str(doc_type).lower()
        if partition not in ("doc", "sheet", "pdf"):
            partition = "doc"

        data = [
            grp["id"].tolist(),
            grp["source_file_id"].tolist(),
            grp["source_name"].tolist(),
            grp["document_type"].tolist(),
            grp["section_title"].tolist(),
            grp["chunk_index"].astype(int).tolist(),
            grp["text"].tolist(),
            [list(map(float, e)) for e in grp["embedding"]],
        ]
        col.insert(data, partition_name=partition)

    inserted += len(batch_df)
    pct = 100 * inserted // total
    print(f"  {inserted:,} / {total:,}  ({pct}%)", end="\r", flush=True)

col.flush()
col.load()
print(f"\n  Restore complete: {total:,} vectors loaded into Milvus")
PYEOF

    docker compose exec -T dashboard-api rm -f /tmp/milvus_restore.parquet
    echo "  OK  Milvus restored"
elif [[ "$DO_MILVUS" == "false" ]]; then
    echo ""
    echo "[4] Skipping Milvus  (--only-* flag active)"
else
    echo ""
    echo "  --  milvus_vectors.parquet not found, skipping"
fi

echo ""
echo "=== Restore complete ==="
echo "Run 'curl -k https://localhost:8000/status' to verify."
