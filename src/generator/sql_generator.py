from __future__ import annotations

import re

import structlog

from src.rag.llm_client import LLMClient
from src.rag.retriever import RetrievedChunk, Retriever

logger = structlog.get_logger()

ALLOWED_SQL_PREFIXES = ("CREATE TABLE", "INSERT INTO", "ALTER TABLE", "CREATE INDEX")
FORBIDDEN_SQL_PATTERNS = re.compile(
    r"\b(DROP|DELETE|TRUNCATE|UPDATE|GRANT|REVOKE|ALTER\s+ROLE|CREATE\s+ROLE)\b",
    re.IGNORECASE,
)


class SQLGenerator:
    def __init__(self, retriever: Retriever, llm: LLMClient) -> None:
        self._retriever = retriever
        self._llm = llm

    async def discover_schema(self, description: str, top_k: int = 20) -> str:
        """Analyze document chunks and propose a SQL schema."""
        chunks = await self._retriever.retrieve(description, top_k=top_k)
        context = "\n\n".join([c.text for c in chunks])

        prompt = (
            "Analyze these document chunks and propose a SQL table schema that captures the structured data.\n"
            "Return only valid SQL CREATE TABLE statements. No explanation.\n"
            "Do NOT include DROP, DELETE, UPDATE, TRUNCATE, or any data-modification statements.\n"
            f"Chunks:\n{context}\n\n"
            f"User description: {description}"
        )

        response = await self._llm.chat([{"role": "user", "content": prompt}])
        
        # Validation
        valid_statements = []
        for line in response.split(";"):
            stmt = line.strip()
            if not stmt:
                continue
            if self.validate_statement(stmt):
                valid_statements.append(stmt)
            else:
                logger.warning("sql_gen.rejected_schema_statement", sql=stmt[:100])

        return ";\n".join(valid_statements) + ";" if valid_statements else ""

    async def extract_data(
        self, chunks: list[RetrievedChunk], schema: str, batch_size: int = 10
    ) -> list[str]:
        """Extract structured data from chunks into INSERT statements."""
        all_inserts = []
        rejected_count = 0

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            context = "\n\n".join([c.text for c in batch])

            prompt = (
                "Based on the provided schema, extract structured data from these chunks into SQL INSERT statements.\n"
                "Return only valid SQL statements. No explanation.\n"
                f"Schema:\n{schema}\n\n"
                f"Chunks:\n{context}"
            )

            response = await self._llm.chat([{"role": "user", "content": prompt}])
            
            for line in response.split(";"):
                stmt = line.strip()
                if not stmt:
                    continue
                if self.validate_statement(stmt):
                    all_inserts.append(stmt)
                else:
                    rejected_count += 1
                    logger.warning("sql_gen.rejected_data_statement", sql=stmt[:100])

        logger.info(
            "sql_gen.extracted", total_inserts=len(all_inserts), rejected=rejected_count
        )
        return all_inserts

    @staticmethod
    def validate_statement(sql: str) -> bool:
        """Return True only if the statement is safe to execute."""
        # Strip comments
        clean_sql = re.sub(r"--.*", "", sql)
        stripped = clean_sql.strip().upper()
        
        if not stripped:
            return False

        if FORBIDDEN_SQL_PATTERNS.search(stripped):
            return False
        
        return any(stripped.startswith(prefix) for prefix in ALLOWED_SQL_PREFIXES)
