"""Tests for src/metadata/repository.py — turns GREEN in Phase 3."""

from __future__ import annotations


from src.metadata.repository import MetadataRepository


class TestMetadataRepository:
    async def test_create_file_record(self, db_session):
        repo = MetadataRepository(db_session)
        record = await repo.create_file_record(drive_file_id="abc123", name="test.pdf", mime_type="application/pdf")
        assert record.status == "pending"
        assert record.drive_file_id == "abc123"

    async def test_get_file_by_drive_id(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="abc123", name="test.pdf", mime_type="application/pdf")
        record = await repo.get_file("abc123")
        assert record is not None
        assert record.name == "test.pdf"

    async def test_update_status(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="abc123", name="test.pdf", mime_type="application/pdf")
        await repo.update_status("abc123", "downloaded")
        record = await repo.get_file("abc123")
        assert record.status == "downloaded"

    async def test_update_status_with_error(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="abc123", name="test.pdf", mime_type="application/pdf")
        await repo.update_status("abc123", "failed", error_message="Download timeout")
        record = await repo.get_file("abc123")
        assert record.status == "failed"
        assert record.error_message == "Download timeout"

    async def test_list_files_by_status(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="a", name="a.pdf", mime_type="application/pdf")
        await repo.create_file_record(drive_file_id="b", name="b.pdf", mime_type="application/pdf")
        await repo.update_status("a", "downloaded")
        results = await repo.list_by_status("pending")
        assert len(results) == 1
        assert results[0].drive_file_id == "b"

    async def test_upsert_on_conflict(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="abc123", name="old.pdf", mime_type="application/pdf")
        await repo.upsert_file(drive_file_id="abc123", name="new.pdf", mime_type="application/pdf")
        record = await repo.get_file("abc123")
        assert record.name == "new.pdf"

    async def test_update_chunk_count(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="abc123", name="test.pdf", mime_type="application/pdf")
        await repo.update_chunk_count("abc123", 42)
        record = await repo.get_file("abc123")
        assert record.chunk_count == 42

    async def test_get_or_create_page_token(self, db_session):
        repo = MetadataRepository(db_session)
        token = await repo.get_page_token()
        assert token is not None

    async def test_update_page_token(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.update_page_token("new-token-123")
        token = await repo.get_page_token()
        assert token == "new-token-123"
