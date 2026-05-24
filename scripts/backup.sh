#!/usr/bin/env bash
# backup.sh — Point-in-time backup: PostgreSQL + MinIO texts + Milvus vectors (parquet)
#
# Usage:
#   ./scripts/backup.sh                    # fast backup — DB + texts + vectors
#   ./scripts/backup.sh --include-raw      # also backup raw-files bucket (~4 GB extra)
#   ./scripts/backup.sh --dest /mnt/nas    # custom root directory
#
# Output structure:
#   backups/YYYYMMDD_HHMMSS/
#     postgres.sql.gz              — full DB dump (--clean --if-exists)
#     minio_converted_texts.tar.gz — extracted texts from MinIO
#     milvus_vectors.parquet       — all vectors with metadata (portable)
#     minio_raw_files.tar.gz       — original documents (only with --include-raw)
#     manifest.json                — sizes, counts, timestamp
#
# Restore with: ./scripts/restore.sh backups/YYYYMMDD_HHMMSS
set -euo pipefail

# ── Parse args ────────────────────────────────────────────────────────────────
INCLUDE_RAW=false
BACKUP_ROOT="./backups"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --include-raw)     INCLUDE_RAW=true;        shift ;;
        --dest)            BACKUP_ROOT="$2";        shift 2 ;;
        --dest=*)          BACKUP_ROOT="${1#*=}";   shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"
mkdir -p "$BACKUP_DIR"

echo "=== RAG Darovi backup — $TIMESTAMP ==="
echo "Destination: $BACKUP_DIR"
echo ""

# ── 1. PostgreSQL ─────────────────────────────────────────────────────────────
echo "[1/4] PostgreSQL dump..."
docker compose exec -T postgres \
    pg_dump -U postgres --clean --if-exists rag_darovi \
    | gzip -6 > "$BACKUP_DIR/postgres.sql.gz"
PG_SIZE=$(du -sh "$BACKUP_DIR/postgres.sql.gz" | cut -f1)
echo "  OK  postgres.sql.gz  ($PG_SIZE)"

# ── 2. MinIO converted-texts ──────────────────────────────────────────────────
echo ""
echo "[2/4] MinIO converted-texts..."
# mc mirror inside the minio container writes to /tmp, then tar is piped to stdout → host file
docker compose exec -T minio sh -c '
    mc alias set local http://localhost:9000 minioadmin minioadmin --quiet 2>/dev/null || true
    rm -rf /tmp/cts-bak
    mc mirror --quiet local/converted-texts /tmp/cts-bak 2>/dev/null
    tar czf - -C /tmp/cts-bak .
    rm -rf /tmp/cts-bak
' > "$BACKUP_DIR/minio_converted_texts.tar.gz"
CTS_SIZE=$(du -sh "$BACKUP_DIR/minio_converted_texts.tar.gz" | cut -f1)
echo "  OK  minio_converted_texts.tar.gz  ($CTS_SIZE)"

# ── 3. Milvus vectors → parquet ───────────────────────────────────────────────
echo ""
echo "[3/4] Milvus vector export (parquet)..."

docker compose exec -T dashboard-api python3 << 'PYEOF'
import sys
import warnings
warnings.filterwarnings("ignore")

from pymilvus import connections, Collection, utility

connections.connect(host="milvus", port="19530")

COL_NAME = "rag_documents"
if not utility.has_collection(COL_NAME):
    print(f"  ERROR: collection '{COL_NAME}' not found", file=sys.stderr)
    sys.exit(1)

col = Collection(COL_NAME)
col.load()
total = int(col.num_entities)
print(f"  {total:,} vectors in collection", flush=True)

import pandas as pd

rows = []
batch = 5000
offset = 0

while True:
    chunk = col.query(
        expr="chunk_index >= 0",
        output_fields=["id", "source_file_id", "source_name", "document_type",
                       "section_title", "chunk_index", "text", "embedding"],
        offset=offset,
        limit=batch,
    )
    if not chunk:
        break
    rows.extend(chunk)
    offset += len(chunk)
    pct = 100 * offset // max(total, 1)
    print(f"  {offset:,} / {total:,}  ({pct}%)", end="\r", flush=True)
    if len(chunk) < batch:
        break

df = pd.DataFrame(rows)
df.to_parquet("/tmp/milvus_vectors.parquet", index=False, engine="pyarrow")
mb = df.memory_usage(deep=True).sum() / 1_000_000
print(f"\n  Exported {len(df):,} rows  ({mb:.0f} MB in-memory)")
PYEOF

DASHBOARD_CONTAINER=$(docker compose ps -q dashboard-api)
docker cp "$DASHBOARD_CONTAINER:/tmp/milvus_vectors.parquet" \
    "$BACKUP_DIR/milvus_vectors.parquet"
docker compose exec -T dashboard-api rm -f /tmp/milvus_vectors.parquet

MV_SIZE=$(du -sh "$BACKUP_DIR/milvus_vectors.parquet" | cut -f1)
echo "  OK  milvus_vectors.parquet  ($MV_SIZE)"

# ── 4. MinIO raw-files (optional) ─────────────────────────────────────────────
if [[ "$INCLUDE_RAW" == "true" ]]; then
    echo ""
    echo "[4/4] MinIO raw-files (this may take several minutes for large buckets)..."
    docker compose exec -T minio sh -c '
        mc alias set local http://localhost:9000 minioadmin minioadmin --quiet 2>/dev/null || true
        rm -rf /tmp/raw-bak
        mc mirror --quiet local/raw-files /tmp/raw-bak 2>/dev/null
        tar czf - -C /tmp/raw-bak .
        rm -rf /tmp/raw-bak
    ' > "$BACKUP_DIR/minio_raw_files.tar.gz"
    RAW_SIZE=$(du -sh "$BACKUP_DIR/minio_raw_files.tar.gz" | cut -f1)
    echo "  OK  minio_raw_files.tar.gz  ($RAW_SIZE)"
else
    echo ""
    echo "[4/4] Skipping raw-files  (re-run with --include-raw to include original PDFs)"
fi

# ── Manifest ──────────────────────────────────────────────────────────────────
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)

python3 - "$BACKUP_DIR" "$TIMESTAMP" "$INCLUDE_RAW" << 'PYJSON'
import json, sys, os, datetime

backup_dir, ts, include_raw = sys.argv[1], sys.argv[2], sys.argv[3]

files = {}
for f in os.listdir(backup_dir):
    if f == "manifest.json":
        continue
    path = os.path.join(backup_dir, f)
    files[f] = os.path.getsize(path)

manifest = {
    "timestamp": ts,
    "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    "includes_raw_files": include_raw == "true",
    "files": files,
}
with open(os.path.join(backup_dir, "manifest.json"), "w") as fh:
    json.dump(manifest, fh, indent=2)
print("  OK  manifest.json")
PYJSON

echo ""
echo "=== Backup complete ($TOTAL_SIZE total) ==="
ls -lh "$BACKUP_DIR/"
