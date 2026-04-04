from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.generator.sql_generator import SQLGenerator

logger = structlog.get_logger()


class DBWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, sql: str) -> None:
        """Execute a single SQL statement after validation."""
        if not SQLGenerator.validate_statement(sql):
            logger.warning("db_writer.rejected_statement", sql=sql[:100])
            raise ValueError("Forbidden SQL statement rejected.")

        try:
            await self._session.execute(text(sql))
            await self._session.commit()
            logger.info("db_writer.executed", sql=sql[:50])
        except Exception as exc:
            await self._session.rollback()
            logger.error("db_writer.execute_error", error=str(exc))
            raise

    async def execute_many(self, statements: list[str]) -> int:
        """Execute multiple SQL statements in a single transaction after validation."""
        valid_statements = []
        for stmt in statements:
            if SQLGenerator.validate_statement(stmt):
                valid_statements.append(stmt)
            else:
                logger.warning("db_writer.rejected_statement_in_batch", sql=stmt[:100])
                # Batch rejection if any are forbidden
                raise ValueError(f"Forbidden SQL statement rejected: {stmt[:50]}...")

        if not valid_statements:
            return 0

        try:
            for stmt in valid_statements:
                await self._session.execute(text(stmt))
            await self._session.commit()
            logger.info("db_writer.executed_many", count=len(valid_statements))
            return len(valid_statements)
        except Exception as exc:
            await self._session.rollback()
            logger.error("db_writer.execute_many_error", error=str(exc))
            raise
