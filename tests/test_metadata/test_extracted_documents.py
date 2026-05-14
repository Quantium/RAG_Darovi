"""Tests for ExtractedDocument repository methods (async + sync upsert)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.metadata.repository import MetadataRepository


class TestExtractedDocumentRepository:
    async def test_upsert_inserts_new_row(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="file-1", name="invoice.pdf", mime_type="application/pdf")

        await repo.upsert_extracted_document(
            "file-1",
            document_type="invoice",
            issuer="ACME Corp",
            issued_at=date(2026, 4, 15),
            total_amount=Decimal("1234.56"),
            currency="USD",
            parties=["ACME Corp", "Buyer Inc"],
            extras={"po_number": "PO-9001"},
        )

        row = await repo.get_extracted_document("file-1")
        assert row is not None
        assert row.issuer == "ACME Corp"
        assert row.issued_at == date(2026, 4, 15)
        assert Decimal(str(row.total_amount)) == Decimal("1234.56")
        assert row.parties == ["ACME Corp", "Buyer Inc"]
        assert row.extras == {"po_number": "PO-9001"}

    async def test_upsert_updates_existing_row(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="file-2", name="x.pdf", mime_type="application/pdf")

        await repo.upsert_extracted_document("file-2", issuer="Old", currency="USD")
        await repo.upsert_extracted_document("file-2", issuer="New", currency="EUR", parties=["P1"])

        row = await repo.get_extracted_document("file-2")
        assert row.issuer == "New"
        assert row.currency == "EUR"
        assert row.parties == ["P1"]

    async def test_upsert_handles_none_optional_fields(self, db_session):
        repo = MetadataRepository(db_session)
        await repo.create_file_record(drive_file_id="file-3", name="x.pdf", mime_type="application/pdf")

        await repo.upsert_extracted_document("file-3")
        row = await repo.get_extracted_document("file-3")
        assert row is not None
        assert row.issuer is None
        assert row.parties == []
        assert row.extras == {}
