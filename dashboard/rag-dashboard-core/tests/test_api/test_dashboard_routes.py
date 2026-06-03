"""Tests for dashboard control panel API."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.dashboard_schemas import DashboardState


_COUNTS = {
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
    "vision_pending_files": 0,
    "vision_processing_files": 0,
}


def _patch_state(tenant, *, raw=5, text=4, vectors=7):
    """Build the stacked patches the dashboard_state endpoint needs, scoped to `tenant`."""
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(
        patch("src.api.dashboard_routes._resolve_dashboard_tenant", new_callable=AsyncMock, return_value=tenant)
    )
    stack.enter_context(
        patch(
            "src.api.dashboard_routes._scoped_pg_counts",
            new_callable=AsyncMock,
            return_value=(_COUNTS, {}, False, False),
        )
    )
    mio = stack.enter_context(patch("src.api.dashboard_routes.MinIOStorage"))
    mio.return_value.count_objects.side_effect = [raw, text]
    probe = stack.enter_context(patch("src.api.dashboard_routes.ProcessingProbe"))
    probe.return_value.celery_flags.return_value = (False, False, None)
    sc = stack.enter_context(patch("src.api.dashboard_routes.SourceCounter"))
    sc.return_value.count.return_value = (100, "file:///data")
    cv = stack.enter_context(patch("src.api.dashboard_routes._count_vectors", return_value=vectors))
    return stack, mio, sc, cv


@pytest.mark.integration
async def test_dashboard_state_returns_contract(app_mocked):
    """Verify GET /dashboard/state returns a valid DashboardState schema with correct card counts."""
    from src.api.dashboard_routes import DashboardTenant

    app_mocked.state.redis_cache.scan_iter.side_effect = [iter([]), iter([])]
    tenant = DashboardTenant(slug="", schema_name="public", collection="rag_documents", source_path="")

    stack, _mio, _sc, _cv = _patch_state(tenant)
    with stack:
        async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
            response = await client.get("/dashboard/state")

    assert response.status_code == 200
    body = response.json()
    validated = DashboardState.model_validate(
        {**body, "updated_at": datetime.fromisoformat(body["updated_at"].replace("Z", "+00:00"))}
    )
    assert validated.cards.postgres_total == 3
    assert validated.cards.minio_raw_total == 5
    assert validated.cards.minio_text_total == 4
    assert validated.cards.milvus_vectors == 7
    assert validated.source_url == "file:///data"


@pytest.mark.integration
async def test_dashboard_state_scopes_to_licitacion(app_mocked):
    """Verify ?licitacion= scopes MinIO prefix, source subfolder, and Milvus collection."""
    from src.api import dashboard_routes
    from src.api.dashboard_routes import DashboardTenant

    app_mocked.state.redis_cache.scan_iter.side_effect = [iter([]), iter([])]
    tenant = DashboardTenant(
        slug="obra_norte", schema_name="lic_obra_norte", collection="rag_obra_norte", source_path="ObraNorte"
    )

    stack, mio, sc, cv = _patch_state(tenant)
    with stack:
        resolve = dashboard_routes._resolve_dashboard_tenant
        async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
            response = await client.get("/dashboard/state?licitacion=obra_norte")

    assert response.status_code == 200
    body = response.json()
    assert body["selected_licitacion"] == "obra_norte"
    # Resolution received the requested slug.
    assert resolve.await_args.args[1] == "obra_norte"
    # MinIO counts were scoped to the licitación key prefix.
    assert mio.return_value.count_objects.call_args_list[0].kwargs["prefix"] == "obra_norte/"
    # Source counter was scoped to the licitación subfolder.
    assert sc.return_value.count.call_args.kwargs["sub_path"] == "ObraNorte"
    # Milvus count targeted the licitación collection.
    assert cv.call_args.args[1] == "rag_obra_norte"


@pytest.mark.integration
async def test_dashboard_re_ingest_requires_confirm(app_mocked):
    """Verify POST /dashboard/re-ingest returns HTTP 400 without the X-Dashboard-Confirm header."""
    async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
        res = await client.post("/dashboard/re-ingest")
        assert res.status_code == 400
