"""Tests for src/generator/db_writer.py — turns GREEN in Phase 6."""
from __future__ import annotations

import pytest

from src.generator.db_writer import DBWriter


class TestDBWriter:
    async def test_execute_create_table(self, db_session):
        writer = DBWriter(session=db_session)
        # Use a unique table name per test to avoid conflicts with physical test.db
        await writer.execute("CREATE TABLE test_tbl_create (id INTEGER PRIMARY KEY, name TEXT)")

    async def test_execute_insert(self, db_session):
        writer = DBWriter(session=db_session)
        await writer.execute("CREATE TABLE test_tbl_insert (id INTEGER PRIMARY KEY, name TEXT)")
        count = await writer.execute_many([
            "INSERT INTO test_tbl_insert VALUES (1, 'Alice')",
            "INSERT INTO test_tbl_insert VALUES (2, 'Bob')"
        ])
        assert count == 2

    async def test_rollback_on_error(self, db_session):
        writer = DBWriter(session=db_session)
        with pytest.raises(Exception):
            # Non-existent table should trigger error and rollback
            await writer.execute("INSERT INTO nonexistent_table VALUES (1)")
