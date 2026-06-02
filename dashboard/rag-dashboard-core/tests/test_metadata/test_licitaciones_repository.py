"""Tests for the licitaciones registry repositories (async + sync)."""

from __future__ import annotations

from src.metadata.repository import (
    LICITACION_STATUS_ACTIVE,
    LICITACION_STATUS_ARCHIVED,
    LICITACION_STATUS_PAUSED,
    Base,
    Licitacion,
    LicitacionRepository,
    SyncLicitacionReader,
)


async def _add(session, **kw) -> None:
    session.add(Licitacion(**kw))
    await session.commit()


class TestLicitacionRepository:
    async def test_list_active_excludes_paused_and_archived(self, db_session) -> None:
        await _add(db_session, id="1", name="Active One", slug="active_one", schema_name="lic_active_one", milvus_collection="rag_active_one", status=LICITACION_STATUS_ACTIVE)
        await _add(db_session, id="2", name="Paused", slug="paused", schema_name="lic_paused", milvus_collection="rag_paused", status=LICITACION_STATUS_PAUSED)
        await _add(db_session, id="3", name="Archived", slug="archived", schema_name="lic_archived", milvus_collection="rag_archived", status=LICITACION_STATUS_ARCHIVED)
        repo = LicitacionRepository(db_session)
        active = await repo.list_active()
        assert [lic.slug for lic in active] == ["active_one"]

    async def test_list_all_excludes_archived_by_default(self, db_session) -> None:
        await _add(db_session, id="1", name="A", slug="a", schema_name="lic_a", milvus_collection="rag_a", status=LICITACION_STATUS_ACTIVE)
        await _add(db_session, id="2", name="Z Arch", slug="z_arch", schema_name="lic_z", milvus_collection="rag_z", status=LICITACION_STATUS_ARCHIVED)
        repo = LicitacionRepository(db_session)
        assert [lic.slug for lic in await repo.list_all()] == ["a"]
        assert {lic.slug for lic in await repo.list_all(include_archived=True)} == {"a", "z_arch"}

    async def test_get_by_slug_and_id(self, db_session) -> None:
        await _add(db_session, id="42", name="Find Me", slug="find_me", schema_name="lic_find_me", milvus_collection="rag_find_me", status=LICITACION_STATUS_ACTIVE)
        repo = LicitacionRepository(db_session)
        by_slug = await repo.get_by_slug("find_me")
        assert by_slug is not None and by_slug.id == "42"
        by_id = await repo.get_by_id("42")
        assert by_id is not None and by_id.slug == "find_me"
        assert await repo.get_by_slug("nope") is None


class TestSyncLicitacionReader:
    def test_list_active_and_get_by_slug(self, tmp_path) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        engine = create_engine(f"sqlite:///{tmp_path / 'sync.db'}")
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            s.add(Licitacion(id="1", name="Act", slug="act", schema_name="lic_act", milvus_collection="rag_act", status=LICITACION_STATUS_ACTIVE))
            s.add(Licitacion(id="2", name="Arc", slug="arc", schema_name="lic_arc", milvus_collection="rag_arc", status=LICITACION_STATUS_ARCHIVED))
            s.commit()
        with Session(engine) as s:
            reader = SyncLicitacionReader(s)
            assert [lic.slug for lic in reader.list_active()] == ["act"]
            found = reader.get_by_slug("act")
            assert found is not None and found.id == "1"
            assert reader.get_by_slug("none") is None
        engine.dispose()
