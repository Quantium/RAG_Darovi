# file_records backfill — Milvus / embedding pipeline blockage

Operational guide for rows stuck after RAW/TEXT metadata diverged from MinIO (for example `status='converted'`, `raw_status='pending'`, `text_status='pending'`, `chunk_count=0`, while `minio_raw_key` / `minio_text_key` are set).

## How the pipeline selects work

### `extract_text` (candidate query)

`services/extract_text` only processes rows where RAW is marked complete and checksummed, and TEXT is out of date or not yet extracted:

```sql
-- Logical equivalent of list_raw_changed_candidates (see services/extract_text/app/db.py)
SELECT ...
FROM file_records
WHERE
    raw_status = 'synced'
    AND minio_raw_key IS NOT NULL
    AND raw_checksum IS NOT NULL
    AND (
        text_source_checksum IS NULL
        OR text_source_checksum <> raw_checksum
        OR text_status IN ('pending', 'failed')
    );
```

If `raw_status` stays `pending` or `raw_checksum` is NULL, **no row is ever selected** for extraction, so `text_status` never becomes `ready_for_embedding`.

### `ingest_raw` (how RAW stage should look)

On successful upload, `update_raw_stage` sets `raw_status='synced'`, fills `raw_checksum` (SHA-256 hex of file bytes), `raw_synced_at`, `minio_raw_key`, `raw_source_version`, resets `text_status` to `pending`, and sets top-level `status` to **`downloaded`** (not `converted`). See `services/ingest_raw/app/db.py`.

New inserts default `raw_status` and `text_status` to `'pending'` (`upsert_file`).

### Legacy worker (`poll_text_ready_for_embedding`)

`SyncMetadataRepository.list_ready_for_embedding_sync` selects `text_status == 'ready_for_embedding'` only (`dashboard/rag-dashboard-core/src/metadata/repository.py`). Nothing is dispatched to Milvus until TEXT reaches that state.

### Schema reference (`file_records`)

From `schema/rag-schema/alembic/versions/20260515_0001_baseline_schema.py`:

- `raw_checksum`, `text_checksum`, `text_source_checksum`: nullable `String(128)` — store **64-character hex** SHA-256 digests as produced by ingest/extract services.
- `raw_status`, `text_status`, `status`: strings; `raw_status` / `text_status` have server default `'pending'`.
- Timestamps (`raw_synced_at`, `text_extracted_at`, `last_processed_at`, etc.) are SQLAlchemy `DateTime` without timezone flag in migrations (PostgreSQL `timestamp without time zone`).

## Preconditions

1. **Snapshot or backup** the Postgres database (or at least `file_records`) before any mass `UPDATE`.
2. Run diagnostics in a **read-only** session first (below).
3. Confirm MinIO still has the objects referenced by `minio_raw_key` (and, if you rely on existing TEXT, `minio_text_key`).
4. Do **not** invent checksums from `minio_raw_key` or random SQL — `raw_checksum` must equal `SHA256(raw_bytes)` from the object in the RAW bucket, or extraction will stay inconsistent.

## Dry-run diagnostics

Adjust filters to match your incident cohort.

```sql
-- Rough “stuck” profile (tune predicates as needed)
SELECT COUNT(*) AS stuck
FROM file_records
WHERE
    chunk_count = 0
    AND minio_raw_key IS NOT NULL
    AND COALESCE(raw_status, 'pending') <> 'synced';

SELECT COUNT(*) AS missing_raw_checksum
FROM file_records
WHERE
    minio_raw_key IS NOT NULL
    AND raw_checksum IS NULL;

SELECT COUNT(*) AS extract_would_ignore
FROM file_records
WHERE
    minio_raw_key IS NOT NULL
    AND (
        COALESCE(raw_status, 'pending') <> 'synced'
        OR raw_checksum IS NULL
    );

-- Sample IDs
SELECT drive_file_id, status, raw_status, text_status,
       raw_checksum IS NOT NULL AS has_raw_checksum,
       minio_raw_key, minio_text_key, chunk_count
FROM file_records
WHERE chunk_count = 0
  AND minio_raw_key IS NOT NULL
ORDER BY drive_file_id
LIMIT 25;
```

## Remediation options

### Option A (recommended): Fix `ingest-raw-service` filesystem + re-drive ingest

Broken local ingest (`LOCAL_SOURCE_FOLDER=/app/LICITACIONES` with **no volume**) leaves DB without `update_raw_stage`. After mounting the host folder, **`ingest_raw` re-processes** any file whose stored row is not `raw_status='synced'` with the same `raw_source_version` as the source (see `_is_unchanged` in `services/ingest_raw/app/service.py` — `pending` is never “unchanged”, so rows get `update_raw_stage` again).

1. Apply the Compose snippet below (set host path via env).
2. `docker compose up -d ingest-raw-service` (or restart it).
3. Watch logs; confirm `updated` > 0 when expected.
4. Ensure `extract-text-service` is running; confirm rows move to `text_status='ready_for_embedding'`.
5. Confirm legacy worker / embedding consumes `ready_for_embedding` and `chunk_count` increases.

**No SQL backfill required** if ingest can see the same files and MinIO upload succeeds.

### Option B (SQL-only, narrow): Mark RAW synced when `raw_checksum` is already correct

Use only when you have independently verified that `raw_checksum` matches the RAW object (for example you computed SHA-256 from `mc cat` / `aws s3api` / a one-off script).

```sql
-- Preview
SELECT drive_file_id, raw_status, raw_checksum, minio_raw_key
FROM file_records
WHERE
    minio_raw_key IS NOT NULL
    AND raw_checksum IS NOT NULL
    AND COALESCE(raw_status, 'pending') IS DISTINCT FROM 'synced';

-- Apply (single transaction; adjust WHERE)
BEGIN;
UPDATE file_records
SET
    raw_status = 'synced',
    raw_synced_at = COALESCE(raw_synced_at, NOW() AT TIME ZONE 'UTC')
WHERE
    minio_raw_key IS NOT NULL
    AND raw_checksum IS NOT NULL
    AND COALESCE(raw_status, 'pending') IS DISTINCT FROM 'synced';
-- REVIEW: SELECT COUNT(*) ... COMMIT or ROLLBACK;
COMMIT;
```

### Option C: Populate `raw_checksum` from MinIO, then Option B

When `raw_checksum` IS NULL but the object exists:

1. For each `minio_raw_key`, download from the RAW bucket and compute `sha256sum` (64 hex chars).
2. Update in batches:

```sql
BEGIN;
UPDATE file_records
SET
    raw_checksum = :hex64,  -- per-row parameter from your script
    raw_status = 'synced',
    raw_synced_at = COALESCE(raw_synced_at, NOW() AT TIME ZONE 'UTC')
WHERE drive_file_id = :id;
COMMIT;
```

Automating this in a small Python script (MinIO SDK + same SHA-256 as `ingest_raw`) is safer than manual SQL row-by-row.

### Option D (advanced, risky): Skip `extract_text` and set `ready_for_embedding`

Only if TEXT objects in MinIO are **proven** correct for the current RAW (same logical file). You must set:

- `text_source_checksum` = current `raw_checksum` (after RAW is correct),
- `text_checksum` = SHA-256 hex of the **text bytes** in the TEXT bucket,
- `text_status` = `'ready_for_embedding'`,
- `text_error` = NULL,
- `text_extracted_at` = appropriate timestamp.

If `text_checksum` does not match real object bytes, downstream quality and idempotency break. Prefer letting `extract_text` run once RAW metadata is fixed.

### Optional: Normalize inconsistent top-level `status`

If `status='converted'` while RAW/TEXT stages are still `pending`, that is inconsistent with service code paths (`mark_text_ready` sets `converted`; ingest sets `downloaded`). After fixing RAW, consider aligning to `downloaded` until extraction completes:

```sql
-- Preview only
SELECT drive_file_id, status, raw_status, text_status
FROM file_records
WHERE status = 'converted'
  AND COALESCE(raw_status, 'pending') <> 'synced';
```

Apply only if you accept resetting UI semantics; many flows key off `text_status` more than `status`.

## Docker Compose: mount local sources into `ingest-raw-service`

The orchestrator Compose file defines `ingest-raw-service` but does **not** mount a host directory. When `INGEST_SOURCE=local` and `LOCAL_SOURCE_FOLDER=/app/LICITACIONES`, you must map a host tree into the container at that path.

Add to **your** `.env` (not committed):

```bash
# Absolute path on the host where tender/document files live (example)
LOCAL_SOURCE_FOLDER_HOST=/home/you/data/LICITACIONES
```

Patch `docker-compose.yml` under `ingest-raw-service` (illustrative — keep indentation consistent with the file):

```yaml
  ingest-raw-service:
    build:
      context: ./services/ingest_raw
    env_file: .env
    environment:
      DATABASE_URL_SYNC: postgresql+psycopg2://postgres:postgres@postgres:5432/rag_darovi
      MINIO_ENDPOINT: minio:9000
      INGEST_RAW_CRON: ${INGEST_RAW_CRON:-0 * * * *}
      INGEST_RAW_BATCH_SIZE: ${INGEST_RAW_BATCH_SIZE:-200}
      INGEST_RAW_RUN_ON_START: ${INGEST_RAW_RUN_ON_START:-true}
      # Ensure container path matches LOCAL_SOURCE_FOLDER in .env
      LOCAL_SOURCE_FOLDER: /app/LICITACIONES
    volumes:
      - ${LOCAL_SOURCE_FOLDER_HOST:?set LOCAL_SOURCE_FOLDER_HOST in .env}:/app/LICITACIONES:ro
    depends_on:
      postgres:
        condition: service_healthy
      minio:
        condition: service_healthy
```

**You must** set `LOCAL_SOURCE_FOLDER_HOST` to the real directory; `:ro` is recommended if ingest only reads files.

## Optional: timezone / `last_processed_at` note

Writes use **timezone-aware** UTC:

- `MetadataRepository.update_last_processed_at` (async): `dashboard/rag-dashboard-core/src/metadata/repository.py` approximately lines 156–160.
- `SyncMetadataRepository.update_last_processed_at` (sync): same file, approximately lines 395–399.

The ORM maps `last_processed_at` with `DateTime` **without** `timezone=True` on `FileRecord` (see `FileRecord` definition, `drive_modified_at` / `last_processed_at` / `raw_synced_at` / `text_extracted_at`, ~lines 37–50). PostgreSQL columns are therefore untyped “timestamp without time zone”. If you see warnings or comparisons mixing aware and naive datetimes in Python or other services, consider fixing the model to use `DateTime(timezone=True)` in a dedicated schema change (`rag-schema`), not as part of this backfill.

## Summary

| Blocker | Fix |
|--------|-----|
| `raw_status` not `synced` | Volume + re-ingest, or verified SQL / checksum from MinIO |
| `raw_checksum` NULL | Compute from RAW bytes or re-ingest; never hash the key string |
| `text_status` never `ready_for_embedding` | Unblock `extract_text` first; then legacy poll / Milvus |

After remediation, re-run the diagnostic `COUNT` queries and spot-check `chunk_count` / Milvus collection counts.
