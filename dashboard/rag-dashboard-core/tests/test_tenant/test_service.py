"""Unit tests for LicitacionService — orchestration on sqlite with injected provisioners."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.metadata.repository import (
    LICITACION_STATUS_ACTIVE,
    LICITACION_STATUS_ARCHIVED,
    LICITACION_STATUS_FAILED,
    LICITACION_STATUS_PAUSED,
    Base,
    LicitacionRepository,
)
from src.tenant.service import (
    LicitacionConflict,
    LicitacionNotFound,
    LicitacionService,
    LicitacionValidationError,
)


@pytest.fixture
async def engine(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'svc.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def redis_mock():
    r = MagicMock()
    r.scan_iter.return_value = iter([])
    return r


def _make_service(engine, redis_mock, settings):
    schema_prov = AsyncMock()
    coll_prov = MagicMock()
    svc = LicitacionService(
        engine,
        settings,
        redis_mock,
        schema_provisioner=schema_prov,
        collection_provisioner=coll_prov,
    )
    return svc, schema_prov, coll_prov


class TestCreate:
    async def test_create_provisions_and_activates(self, engine, redis_mock, settings):
        svc, schema_prov, coll_prov = _make_service(engine, redis_mock, settings)
        row = await svc.create("Obra Norte 2026", source_path="obra_norte")
        assert row.slug == "obra_norte_2026"
        assert row.schema_name == "lic_obra_norte_2026"
        assert row.milvus_collection == "rag_obra_norte_2026"
        assert row.source_path == "obra_norte"
        assert row.status == LICITACION_STATUS_ACTIVE
        schema_prov.assert_awaited_once()
        assert schema_prov.await_args.args[1] == "lic_obra_norte_2026"
        coll_prov.assert_called_once_with(settings, "rag_obra_norte_2026")

    async def test_duplicate_name_conflicts(self, engine, redis_mock, settings):
        svc, *_ = _make_service(engine, redis_mock, settings)
        await svc.create("Obra Norte")
        with pytest.raises(LicitacionConflict):
            await svc.create("Obra Norte")

    async def test_empty_or_unsluggable_name_validation(self, engine, redis_mock, settings):
        svc, *_ = _make_service(engine, redis_mock, settings)
        with pytest.raises(LicitacionValidationError):
            await svc.create("   ")
        with pytest.raises(LicitacionValidationError):
            await svc.create("!!!")

    async def test_failed_provisioning_marks_failed_then_resumes(self, engine, redis_mock, settings):
        boom = MagicMock(side_effect=RuntimeError("milvus down"))
        svc_fail = LicitacionService(
            engine, settings, redis_mock, schema_provisioner=AsyncMock(), collection_provisioner=boom
        )
        with pytest.raises(RuntimeError):
            await svc_fail.create("Obra Sur")
        async with AsyncSession(engine) as s:
            row = await LicitacionRepository(s).get_by_slug("obra_sur")
            assert row is not None and row.status == LICITACION_STATUS_FAILED

        # A failed row can be resumed by re-creating with the same name (no conflict).
        svc_ok, *_ = _make_service(engine, redis_mock, settings)
        row = await svc_ok.create("Obra Sur")
        assert row.status == LICITACION_STATUS_ACTIVE
        async with AsyncSession(engine) as s:
            rows = await LicitacionRepository(s).list_all(include_archived=True)
            assert len([r for r in rows if r.slug == "obra_sur"]) == 1


class TestEditImmutability:
    async def test_rename_keeps_slug_schema_collection(self, engine, redis_mock, settings):
        svc, *_ = _make_service(engine, redis_mock, settings)
        row = await svc.create("Obra Norte")
        edited = await svc.edit(row.id, name="Obra Norte Renombrada")
        assert edited.name == "Obra Norte Renombrada"
        assert edited.slug == "obra_norte"
        assert edited.schema_name == "lic_obra_norte"
        assert edited.milvus_collection == "rag_obra_norte"

    async def test_edit_not_found(self, engine, redis_mock, settings):
        svc, *_ = _make_service(engine, redis_mock, settings)
        with pytest.raises(LicitacionNotFound):
            await svc.edit("nope", name="x")


class TestPauseResumeArchive:
    async def test_pause_sets_per_slug_redis_flags(self, engine, redis_mock, settings):
        svc, *_ = _make_service(engine, redis_mock, settings)
        row = await svc.create("Obra Norte")
        paused = await svc.pause(row.id)
        assert paused.status == LICITACION_STATUS_PAUSED
        keys = {call.args[0] for call in redis_mock.set.call_args_list}
        assert keys == {
            "rag:pause:ingest:obra_norte",
            "rag:pause:transform:obra_norte",
            "rag:pause:vectorize:obra_norte",
        }

    async def test_resume_clears_redis_flags(self, engine, redis_mock, settings):
        svc, *_ = _make_service(engine, redis_mock, settings)
        row = await svc.create("Obra Norte")
        await svc.pause(row.id)
        resumed = await svc.resume(row.id)
        assert resumed.status == LICITACION_STATUS_ACTIVE
        deleted = {call.args[0] for call in redis_mock.delete.call_args_list}
        assert "rag:pause:ingest:obra_norte" in deleted

    async def test_archive_soft_deletes_keeps_data_and_purges(self, engine, redis_mock, settings):
        svc, *_ = _make_service(engine, redis_mock, settings)
        row = await svc.create("Obra Norte")
        archived = await svc.archive(row.id)
        assert archived.status == LICITACION_STATUS_ARCHIVED
        async with AsyncSession(engine) as s:
            repo = LicitacionRepository(s)
            assert await repo.get_by_id(row.id) is not None  # NOT dropped
            assert row.id not in {r.id for r in await repo.list_all()}
            assert row.id in {r.id for r in await repo.list_all(include_archived=True)}
        redis_mock.scan_iter.assert_called_with(match="chatbot:conv:obra_norte:*")

    async def test_archived_slug_create_conflicts(self, engine, redis_mock, settings):
        svc, *_ = _make_service(engine, redis_mock, settings)
        row = await svc.create("Obra Norte")
        await svc.archive(row.id)
        with pytest.raises(LicitacionConflict):
            await svc.create("Obra Norte")
