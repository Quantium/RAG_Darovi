"""Tests for src/generator/db_writer.py — turns GREEN in Phase 6."""

from __future__ import annotations

import uuid

import pytest

from src.generator.db_writer import DBWriter


class TestDBWriter:
    async def test_execute_create_table(self, db_session):
        """Verify DBWriter.execute can CREATE TABLE without raising."""
        writer = DBWriter(session=db_session)
        # Unique name: custom tables are not in ORM metadata, so drop_all does not remove them
        t = f"test_tbl_create_{uuid.uuid4().hex[:12]}"
        await writer.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY, name TEXT)")

    async def test_execute_insert(self, db_session):
        """Verify execute_many inserts rows and returns the count of executed statements."""
        writer = DBWriter(session=db_session)
        t = f"test_tbl_insert_{uuid.uuid4().hex[:12]}"
        await writer.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY, name TEXT)")
        count = await writer.execute_many(
            [
                f"INSERT INTO {t} VALUES (1, 'Alice')",
                f"INSERT INTO {t} VALUES (2, 'Bob')",
            ]
        )
        assert count == 2

    async def test_rollback_on_error(self, db_session):
        """Verify DBWriter.execute rolls back and raises when executing on a non-existent table."""
        writer = DBWriter(session=db_session)
        with pytest.raises(Exception):
            # Non-existent table should trigger error and rollback
            await writer.execute("INSERT INTO nonexistent_table VALUES (1)")
