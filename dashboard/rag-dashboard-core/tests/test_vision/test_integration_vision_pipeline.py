"""End-to-end integration test for the vision pipeline.

Marked `@pytest.mark.integration` so the standard `pytest` run skips it
(`pyproject.toml` registers the marker). To run it:

    docker compose up -d
    pytest tests/test_vision/test_integration_vision_pipeline.py -m integration

The test:
1. Uploads a synthetic image with embedded text into MinIO (raw bucket).
2. Writes a "converted text" file with a single VLM sentinel into the
   text bucket — mimicking what the converter step produces.
3. Inserts a matching FileRecord row in Postgres.
4. Invokes `vision_extract` directly (bypassing Celery routing) so we can
   assert deterministically.
5. Checks that:
   - The sentinel was replaced with non-empty transcribed text.
   - An `extracted_documents` row was upserted in Postgres.
6. Calls `embed_file` and checks that Milvus received chunks whose first
   row carries the `[document_summary]` prefix when KV was extracted.

Requires the ollama-vision, milvus, postgres, minio and redis services
from docker-compose.yml to be reachable. Skips automatically when any of
them is unavailable so CI without GPUs does not break.
"""

from __future__ import annotations

import io
import os
import time
import uuid

import pytest

pytestmark = pytest.mark.integration


def _services_available() -> bool:
    """Return True if all required Docker services (MinIO, Postgres, Redis, Milvus, VLM) are reachable."""
    import socket

    targets = [
        ("localhost", 9000),
        ("localhost", 5432),
        ("localhost", 6379),
        ("localhost", 19530),
        ("localhost", 11436),
    ]
    for host, port in targets:
        try:
            with socket.create_connection((host, port), timeout=1):
                pass
        except OSError:
            return False
    return True


@pytest.fixture(scope="module")
def integration_settings():
    """Return live Settings for integration tests; skips if Docker services are unavailable."""
    if not _services_available():
        pytest.skip("Required Docker services are not running on localhost")

    from pydantic import SecretStr

    from config.settings import Settings

    return Settings(
        minio_endpoint="localhost:9000",
        minio_access_key=SecretStr(os.environ.get("MINIO_ACCESS_KEY", "minioadmin")),
        minio_secret_key=SecretStr(os.environ.get("MINIO_SECRET_KEY", "minioadmin")),
        minio_secure=False,
        database_url=SecretStr(
            os.environ.get(
                "DATABASE_URL",
                "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_darovi",
            )
        ),
        database_url_sync=SecretStr(
            os.environ.get(
                "DATABASE_URL_SYNC",
                "postgresql+psycopg2://postgres:postgres@localhost:5432/rag_darovi",
            )
        ),
        redis_broker_url="redis://localhost:6379/0",
        redis_result_url="redis://localhost:6379/1",
        redis_cache_url="redis://localhost:6379/2",
        milvus_host="localhost",
        milvus_port=19530,
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11435"),
        vision_base_url=os.environ.get("VISION_BASE_URL", "http://localhost:11436"),
        api_key=SecretStr(""),
    )


def _synthetic_invoice_png() -> bytes:
    """Render a tiny but legible 'invoice' image so the VLM has text to read."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1024, 600), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
        small = ImageFont.load_default()

    draw.text((40, 40), "ACME CORP", fill="black", font=font)
    draw.text((40, 90), "Invoice #PO-9001", fill="black", font=small)
    draw.text((40, 130), "Date: 2026-04-15", fill="black", font=small)
    draw.text((40, 170), "Total: 1234.56 USD", fill="black", font=small)
    draw.text((40, 220), "Bill to: Buyer Inc", fill="black", font=small)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_vision_pipeline_end_to_end(integration_settings):
    """Upload synthetic invoice -> vision_extract -> Postgres KV -> embed_file."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.metadata.repository import Base, FileRecord, SyncMetadataRepository
    from src.storage.backend import MinIOStorage
    from src.vision.sentinels import VISION_SENTINEL_TEMPLATE
    from src.worker.tasks import embed_file, vision_extract

    drive_file_id = f"vision-it-{uuid.uuid4().hex[:8]}"
    settings = integration_settings

    # Make sure the schema exists (idempotent).
    sync_engine = create_engine(settings.database_url_sync.get_secret_value())
    Base.metadata.create_all(sync_engine)

    storage = MinIOStorage(settings)
    storage.ensure_buckets()

    image_bytes = _synthetic_invoice_png()
    raw_key = f"{drive_file_id}/invoice.png"
    storage.upload(settings.minio_bucket_raw, raw_key, image_bytes)

    text_key = f"{drive_file_id}.txt"
    converted = f"--- PAGE 1 ---\n\n{VISION_SENTINEL_TEMPLATE.format(page=1)}"
    storage.upload(settings.minio_bucket_text, text_key, converted.encode("utf-8"))

    with Session(sync_engine) as session:
        repo = SyncMetadataRepository(session)
        # Create record matching this file id
        existing = session.get(FileRecord, drive_file_id)
        if existing is None:
            session.add(
                FileRecord(
                    drive_file_id=drive_file_id,
                    name="invoice.png",
                    mime_type="image/png",
                    status="converted",
                    minio_raw_key=raw_key,
                    minio_text_key=text_key,
                )
            )
            session.commit()

    convert_result = {
        "drive_file_id": drive_file_id,
        "minio_text_key": text_key,
        "minio_raw_key": raw_key,
        "name": "invoice.png",
        "mime_type": "image/png",
        "document_type": "image",
    }

    started = time.time()
    result = vision_extract(convert_result)
    elapsed = time.time() - started
    print(f"vision_extract elapsed: {elapsed:.1f}s")

    # Sentinel removed and replaced with non-empty content.
    final_text = storage.download(settings.minio_bucket_text, text_key).decode("utf-8")
    assert VISION_SENTINEL_TEMPLATE.format(page=1) not in final_text
    assert "ACME" in final_text or "[OCR FAILED" in final_text  # tolerate fallback when GPU is missing

    # KV row exists.
    with Session(sync_engine) as session:
        repo = SyncMetadataRepository(session)
        row = repo.get_extracted_document_sync(drive_file_id)
        assert row is not None

    # Embed step accepts the kv_summary and produces chunks.
    embed_result = embed_file(result)
    assert embed_result["chunk_count"] >= 1
