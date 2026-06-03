"""Stage 4 tests: the dashboard embedding pipeline is scoped per licitación.

Covers collection routing, schema-scoped metadata write-back, per-licitación pause,
registry-driven tenant resolution with a legacy fallback, and tenant-context
propagation through vision_extract and the vision poll.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from pydantic import SecretStr
from sqlalchemy import create_engine, text

from config.settings import Settings
from src.worker.tasks import (
    _embed_and_store,
    embed_file,
    poll_vision_pending,
    vision_extract,
)
from src.worker.tenant_runtime import (
    TenantContext,
    context_from_payload,
    is_vectorize_paused,
    read_active_tenants,
)

TENANT = TenantContext(slug="obra_norte", schema_name="lic_obra_norte", collection="rag_obra_norte")


def _payload(**extra) -> dict:
    base = {
        "drive_file_id": "f1",
        "minio_text_key": "obra_norte/f1.md",
        "minio_raw_key": "obra_norte/f1.pdf",
        "name": "f1.pdf",
        "mime_type": "application/pdf",
        "document_type": "pdf",
        **TENANT.payload(),
    }
    base.update(extra)
    return base


class TestTenantContext:
    def test_payload_round_trips(self):
        assert context_from_payload(TENANT.payload(), Settings()) == TENANT

    def test_missing_keys_default_to_legacy(self):
        ctx = context_from_payload({}, Settings())
        assert ctx.slug == "" and ctx.schema_name == "public"
        assert ctx.collection == Settings().milvus_collection

    def test_vectorize_pause_keys(self):
        assert TENANT.vectorize_pause_keys() == (
            "rag:pause:vectorize",
            "rag:pause:vectorize:obra_norte",
        )
        assert TenantContext.legacy(Settings()).vectorize_pause_keys() == ("rag:pause:vectorize",)

    def test_is_vectorize_paused_global_and_per_slug(self):
        redis_global = MagicMock()
        redis_global.exists.side_effect = lambda k: k == "rag:pause:vectorize"
        assert is_vectorize_paused(redis_global, TENANT) is True

        redis_slug = MagicMock()
        redis_slug.exists.side_effect = lambda k: k == "rag:pause:vectorize:obra_norte"
        assert is_vectorize_paused(redis_slug, TENANT) is True
        # The per-slug pause must not mute a different licitación / the legacy tenant.
        assert is_vectorize_paused(redis_slug, TenantContext.legacy(Settings())) is False


class TestEmbedAndStore:
    async def test_routes_to_tenant_collection_and_schema(self):
        chunks = [
            SimpleNamespace(
                text="body",
                source_file_id="f1",
                source_name="f1.pdf",
                document_type="pdf",
                section_title="",
                chunk_index=0,
            )
        ]
        settings = Settings()
        with patch("src.vectorizer.embedder.BatchEmbedder") as mock_emb_cls, patch(
            "src.vectorizer.milvus_store.MilvusStore"
        ) as mock_store_cls, patch(
            "src.worker.tasks._update_embedded", new=AsyncMock()
        ) as mock_update:
            mock_emb_cls.return_value.embed_texts = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

            count = await _embed_and_store(settings, "f1", chunks, TENANT)

        assert count == 1
        # Vectors go to the licitación's collection...
        mock_store_cls.assert_called_once_with(settings, collection_name="rag_obra_norte")
        store = mock_store_cls.return_value
        store.delete_by_source.assert_called_once_with("f1")
        store.upsert.assert_called_once()
        # ...and the metadata write-back targets the licitación's schema.
        mock_update.assert_awaited_once_with(settings, "f1", 1, "lic_obra_norte")


class TestEmbedFilePause:
    def test_skips_when_licitacion_paused(self):
        with patch("src.worker.tasks.build_settings", return_value=Settings()), patch(
            "src.worker.tasks.redis.Redis"
        ) as mock_redis_cls, patch("src.worker.tasks.build_storage") as mock_storage_builder:
            mock_redis_cls.from_url.return_value.exists.side_effect = (
                lambda k: k == "rag:pause:vectorize:obra_norte"
            )
            result = embed_file(_payload())

        assert result == {"skipped": True, "drive_file_id": "f1"}
        # Bailed before doing any storage / embedding work.
        mock_storage_builder.assert_not_called()

    def test_skips_when_global_pause_set(self):
        with patch("src.worker.tasks.build_settings", return_value=Settings()), patch(
            "src.worker.tasks.redis.Redis"
        ) as mock_redis_cls, patch("src.worker.tasks.build_storage") as mock_storage_builder:
            mock_redis_cls.from_url.return_value.exists.side_effect = (
                lambda k: k == "rag:pause:vectorize"
            )
            result = embed_file(_payload())

        assert result["skipped"] is True
        mock_storage_builder.assert_not_called()


class TestReadActiveTenants:
    def test_legacy_fallback_when_table_missing(self):
        engine = create_engine("sqlite://")
        tenants = read_active_tenants(engine, Settings())
        engine.dispose()
        assert len(tenants) == 1
        assert tenants[0] == TenantContext.legacy(Settings())

    def test_returns_only_active_rows(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE licitaciones "
                    "(slug TEXT, schema_name TEXT, milvus_collection TEXT, status TEXT, name TEXT)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO licitaciones VALUES "
                    "('obra_norte','lic_obra_norte','rag_obra_norte','active','Obra Norte'),"
                    "('vieja','lic_vieja','rag_vieja','archived','Vieja')"
                )
            )
        tenants = read_active_tenants(engine, Settings())
        engine.dispose()
        assert [t.slug for t in tenants] == ["obra_norte"]
        assert tenants[0].collection == "rag_obra_norte"
        assert tenants[0].schema_name == "lic_obra_norte"

    def test_legacy_fallback_when_no_active_rows(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE licitaciones "
                    "(slug TEXT, schema_name TEXT, milvus_collection TEXT, status TEXT, name TEXT)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO licitaciones VALUES "
                    "('vieja','lic_vieja','rag_vieja','archived','Vieja')"
                )
            )
        tenants = read_active_tenants(engine, Settings())
        engine.dispose()
        assert tenants == [TenantContext.legacy(Settings())]


class TestVisionExtractTenant:
    @patch("src.worker.tasks.build_tenant_metadata_repo")
    @patch("src.worker.tasks.build_storage")
    @patch("src.worker.tasks.build_settings")
    def test_uses_tenant_schema_and_forwards_context(
        self, mock_settings, mock_storage_builder, mock_repo_builder
    ):
        mock_settings.return_value = Settings()
        mock_storage = MagicMock()
        mock_storage.download.return_value = b"plain text, no sentinels"
        mock_storage_builder.return_value = mock_storage
        mock_repo_builder.return_value = (MagicMock(), lambda: None)

        result = vision_extract(_payload())

        # DB writes are scoped to the file's licitación schema.
        mock_repo_builder.assert_called_once_with(ANY, "lic_obra_norte")
        # Tenant context survives to embed_file (the next link in the chain).
        assert result["slug"] == "obra_norte"
        assert result["schema_name"] == "lic_obra_norte"
        assert result["collection"] == "rag_obra_norte"


class TestPollVisionPendingTenant:
    @patch("src.worker.tasks.chain")
    @patch("src.worker.tasks.build_tenant_metadata_repo")
    @patch("src.worker.tasks.read_active_tenants")
    @patch("src.worker.tasks.build_settings")
    def test_dispatches_per_tenant(
        self, mock_settings, mock_read_tenants, mock_repo_builder, mock_chain
    ):
        mock_settings.return_value = Settings(database_url_sync=SecretStr("sqlite://"))
        mock_read_tenants.return_value = [TENANT]
        record = SimpleNamespace(
            drive_file_id="f1",
            minio_text_key="obra_norte/f1.md",
            minio_raw_key="obra_norte/f1.pdf",
            mime_type="application/pdf",
            name="f1.pdf",
        )
        mock_repo = MagicMock()
        mock_repo.list_vision_pending_sync.return_value = [record]
        mock_repo_builder.return_value = (mock_repo, lambda: None)

        result = poll_vision_pending()

        mock_repo_builder.assert_called_once_with(ANY, "lic_obra_norte")
        mock_repo.update_status_sync.assert_called_once_with("f1", "vision_processing")
        mock_chain.return_value.apply_async.assert_called_once()
        assert result["queued"] == 1
