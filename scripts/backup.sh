#!/usr/bin/env bash
# backup.sh — Point-in-time backup: PostgreSQL + MinIO texts + Milvus vectors (parquet)
#
# Usage:
#   ./scripts/backup.sh                    # fast backup — DB + texts + vectors
#   ./scripts/backup.sh --include-raw      # also backup raw-files bucket (~4 GB extra)
#   ./scripts/backup.sh --dest /mnt/nas    # custom root directory
#   ./scripts/backup.sh --only-postgres    # only PostgreSQL dump
#   ./scripts/backup.sh --only-minio       # only MinIO texts (add --include-raw for raw-files)
#   ./scripts/backup.sh --only-milvus      # only Milvus vectors parquet
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
DO_POSTGRES=true
DO_MINIO=true
DO_MILVUS=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --include-raw)     INCLUDE_RAW=true;                            shift ;;
        --dest)            BACKUP_ROOT="$2";                            shift 2 ;;
        --dest=*)          BACKUP_ROOT="${1#*=}";                       shift ;;
        --only-postgres)   DO_POSTGRES=true;  DO_MINIO=false;  DO_MILVUS=false; shift ;;
        --only-minio)      DO_POSTGRES=false; DO_MINIO=true;   DO_MILVUS=false; shift ;;
        --only-milvus)     DO_POSTGRES=false; DO_MINIO=false;  DO_MILVUS=true;  shift ;;
        --only-fans)       echo "oh! you, nasty"; exit 0 ;;
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
if [[ "$DO_POSTGRES" == "true" ]]; then
    echo "[1/4] PostgreSQL dump..."
    docker compose exec -T postgres \
        pg_dump -U postgres --clean --if-exists rag_darovi \
        | gzip -6 > "$BACKUP_DIR/postgres.sql.gz"
    PG_SIZE=$(du -sh "$BACKUP_DIR/postgres.sql.gz" | cut -f1)
    echo "  OK  postgres.sql.gz  ($PG_SIZE)"
else
    echo "[1/4] Skipping PostgreSQL  (--only-* flag active)"
fi

# ── 2. MinIO converted-texts ──────────────────────────────────────────────────
# Uses Python minio client in dashboard-api (streams tar.gz to stdout → host file).
# The minio container image has no tar binary, so we avoid it entirely.
echo ""
if [[ "$DO_MINIO" == "true" ]]; then
echo "[2/4] MinIO converted-texts..."
docker compose exec -T dashboard-api python3 << 'PYEOF' > "$BACKUP_DIR/minio_converted_texts.tar.gz"
import sys, io, tarfile
from minio import Minio

client = Minio("minio:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
bucket = "converted-texts"

count = 0
tf = tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz")
for obj in client.list_objects(bucket, recursive=True):
    resp = client.get_object(bucket, obj.object_name)
    data = resp.read()
    info = tarfile.TarInfo(name=obj.object_name)
    info.size = len(data)
    info.mtime = int(obj.last_modified.timestamp()) if obj.last_modified else 0
    tf.addfile(info, io.BytesIO(data))
    count += 1
    print(f"  {count}: {obj.object_name}", file=sys.stderr, flush=True)
tf.close()
print(f"  Archived {count} objects", file=sys.stderr)
PYEOF
CTS_SIZE=$(du -sh "$BACKUP_DIR/minio_converted_texts.tar.gz" | cut -f1)
echo "  OK  minio_converted_texts.tar.gz  ($CTS_SIZE)"
else
    echo "[2/4] Skipping MinIO texts  (--only-* flag active)"
fi

# ── 3. Milvus vectors → parquet ───────────────────────────────────────────────
echo ""
if [[ "$DO_MILVUS" == "true" ]]; then
echo "[3/4] Milvus vector export (parquet)..."

docker compose exec -T dashboard-api python3 << 'PYEOF'
import sys, logging, warnings
warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

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

if total == 0:
    import pandas as pd
    pd.DataFrame(columns=["id","source_file_id","source_name","document_type",
                           "section_title","chunk_index","text","embedding"]
                ).to_parquet("/tmp/milvus_vectors.parquet", index=False, engine="pyarrow")
    print("  Collection is empty — wrote empty parquet")
    sys.exit(0)

import pandas as pd

# Use QueryIterator to avoid the Milvus offset+limit <= 16384 hard limit.
# Batch size kept small (200): 200 × (12 KB embedding + text) ≈ 2-5 MB per batch.
BATCH = 200
meta_rows = []
exported = 0

iterator = col.query_iterator(
    expr="chunk_index >= 0",
    output_fields=["id", "source_file_id", "source_name", "document_type",
                   "section_title", "chunk_index", "text", "embedding"],
    batch_size=BATCH,
)

while True:
    batch = iterator.next()
    if not batch:
        iterator.close()
        break
    meta_rows.extend(batch)
    exported += len(batch)
    pct = 100 * exported // max(total, 1)
    print(f"  {exported:,} / {total:,}  ({pct}%)", end="\r", flush=True)

df = pd.DataFrame(meta_rows)
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
else
    echo "[3/4] Skipping Milvus  (--only-* flag active)"
fi

# ── 4. MinIO raw-files (optional) ─────────────────────────────────────────────
if [[ "$DO_MINIO" == "true" && "$INCLUDE_RAW" == "true" ]]; then
    echo ""
    echo "[4/4] MinIO raw-files (this may take several minutes for large buckets)..."
    docker compose exec -T dashboard-api python3 << 'PYEOF' > "$BACKUP_DIR/minio_raw_files.tar.gz"
import sys, io, tarfile
from minio import Minio

client = Minio("minio:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
bucket = "raw-files"

count = 0
tf = tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz")
for obj in client.list_objects(bucket, recursive=True):
    resp = client.get_object(bucket, obj.object_name)
    data = resp.read()
    info = tarfile.TarInfo(name=obj.object_name)
    info.size = len(data)
    info.mtime = int(obj.last_modified.timestamp()) if obj.last_modified else 0
    tf.addfile(info, io.BytesIO(data))
    count += 1
    if count % 50 == 0:
        print(f"  {count} files...", file=sys.stderr, flush=True)
tf.close()
print(f"  Archived {count} objects", file=sys.stderr)
PYEOF
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
    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
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
