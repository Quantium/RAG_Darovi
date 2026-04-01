"""Tests for src/generator/sql_generator.py — turns GREEN in Phase 6."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from src.generator.sql_generator import SQLGenerator


class TestSQLGenerator:
    @pytest.fixture
    def sql_gen(self):
        retriever = AsyncMock()
        llm = AsyncMock()
        return SQLGenerator(retriever=retriever, llm=llm)

    async def test_discover_schema_from_chunks(self, sql_gen):
        sql_gen._llm.chat.return_value = "CREATE TABLE invoices (id INT, amount DECIMAL);"
        sql_gen._retriever.retrieve.return_value = [AsyncMock(text="Invoice #1: $100")]
        schema = await sql_gen.discover_schema("invoices from PDFs")
        assert "CREATE TABLE" in schema

    async def test_generate_inserts_from_chunks(self, sql_gen):
        sql_gen._llm.chat.return_value = "INSERT INTO invoices VALUES (1, 100.0);"
        chunks = [AsyncMock(text="Invoice #1: $100")]
        inserts = await sql_gen.extract_data(chunks, "CREATE TABLE invoices (id INT, amount DECIMAL);")
        assert any("INSERT" in s for s in inserts)

    async def test_handles_inconsistent_data(self, sql_gen):
        sql_gen._llm.chat.return_value = "-- skipped: inconsistent row"
        chunks = [AsyncMock(text="malformed data")]
        inserts = await sql_gen.extract_data(chunks, "CREATE TABLE t (id INT);")
        assert isinstance(inserts, list)

    def test_validate_rejects_drop_table(self):
        from src.generator.sql_generator import SQLGenerator
        assert SQLGenerator.validate_statement("DROP TABLE users;") is False

    def test_validate_rejects_delete(self):
        from src.generator.sql_generator import SQLGenerator
        assert SQLGenerator.validate_statement("DELETE FROM users WHERE id = 1;") is False

    def test_validate_rejects_update(self):
        from src.generator.sql_generator import SQLGenerator
        assert SQLGenerator.validate_statement("UPDATE users SET name = 'x';") is False

    def test_validate_accepts_insert(self):
        from src.generator.sql_generator import SQLGenerator
        assert SQLGenerator.validate_statement("INSERT INTO invoices VALUES (1, 100.0);") is True

    def test_validate_accepts_create_table(self):
        from src.generator.sql_generator import SQLGenerator
        assert SQLGenerator.validate_statement("CREATE TABLE invoices (id INT);") is True
