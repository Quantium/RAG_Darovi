"""Tests for dashboard control panel API."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.dashboard_schemas import DashboardState


@pytest.mark.integration
async def test_dashboard_state_returns_contract(app_mocked):
    """Verify GET /dashboard/state returns a valid DashboardState schema with correct card counts."""
    from src.metadata.repository import MetadataRepository

    mock_redis = app_mocked.state.redis_cache
    mock_redis.scan_iter.side_effect = [iter([]), iter([])]

    counts = {
        "postgres_total": 3,
        "raw_synced": 2,
        "raw_pending": 1,
        "text_ready": 1,
        "text_pending": 0,
        "text_processing_now": 0,
        "text_failed": 0,
        "transform_total": 2,
        "transform_done": 1,
        "milvus_files_vectorized": 0,
        "postgres_to_reprocess": 0,
        "milvus_pending_files": 1,
    }

    with patch.object(MetadataRepository, "get_dashboard_counts", new_callable=AsyncMock, return_value=counts):
        with patch("src.api.dashboard_routes.MinIOStorage") as mio:
            mio.return_value.count_objects.side_effect = [5, 4]
            with patch("src.api.dashboard_routes.ProcessingProbe") as p:
                p.return_value.celery_flags.return_value = (False, False)
                p.return_value.advisory_extract_lock_held = AsyncMock(return_value=False)
                p.return_value.max_raw_synced_recent = AsyncMock(return_value=False)
                with patch("src.api.dashboard_routes.SourceCounter") as sc:
                    sc.return_value.count.return_value = (100, "file:///data")
                    app_mocked.state.vector_store.count_entities.return_value = 7
                    async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                        response = await client.get("/dashboard/state")

    assert response.status_code == 200
    body = response.json()
    validated = DashboardState.model_validate(
        {
            **body,
            "updated_at": datetime.fromisoformat(body["updated_at"].replace("Z", "+00:00")),
        }
    )
    assert validated.cards.postgres_total == 3
    assert validated.cards.minio_raw_total == 5
    assert validated.cards.minio_text_total == 4
    assert validated.cards.milvus_vectors == 7
    assert validated.source_url == "file:///data"


@pytest.mark.integration
async def test_dashboard_re_ingest_requires_confirm(app_mocked):
    """Verify POST /dashboard/re-ingest returns HTTP 400 without the X-Dashboard-Confirm header."""
    async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
        res = await client.post("/dashboard/re-ingest")
        assert res.status_code == 400
