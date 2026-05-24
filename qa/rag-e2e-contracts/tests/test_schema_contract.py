from __future__ import annotations

import os

import psycopg2


DATABASE_DSN = os.getenv("DATABASE_DSN", "postgresql://postgres:postgres@localhost:5432/rag_darovi")


EXPECTED_FILE_RECORD_COLUMNS = {
    "drive_file_id",
    "name",
    "mime_type",
    "drive_modified_at",
    "status",
    "error_message",
    "chunk_count",
    "last_processed_at",
    "minio_raw_key",
    "minio_text_key",
    "raw_source_version",
    "raw_checksum",
    "raw_synced_at",
    "raw_status",
    "text_checksum",
    "text_source_checksum",
    "text_extracted_at",
    "text_status",
    "text_error",
}


def test_file_records_schema_contract() -> None:
    conn = psycopg2.connect(DATABASE_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'file_records'
                """
            )
            columns = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()

    missing = EXPECTED_FILE_RECORD_COLUMNS - columns
    assert not missing, f"Missing columns in file_records: {sorted(missing)}"
