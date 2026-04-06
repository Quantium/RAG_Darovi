from __future__ import annotations

import csv
import io
from typing import Any

import structlog

from src.automation.templates import AutomationConfig, matches_file
from src.generator.db_writer import DBWriter
from src.generator.sheets_writer import SheetsWriter
from src.rag.llm_client import LLMClient
from src.rag.retriever import Retriever

logger = structlog.get_logger()


class AutomationEngine:
    def __init__(
        self,
        retriever: Retriever,
        llm: LLMClient,
        db_writer: DBWriter,
        sheets_writer: SheetsWriter,
        configs: list[AutomationConfig],
    ) -> None:
        self._retriever = retriever
        self._llm = llm
        self._db_writer = db_writer
        self._sheets_writer = sheets_writer
        self._configs = configs

    async def run(self, trigger: str, file_meta: dict[str, Any] | None = None) -> None:
        """Run all automation configurations matching the trigger and file filter."""
        matching_configs = [c for c in self._configs if c.trigger == trigger]

        for config in matching_configs:
            if file_meta and config.filter:
                if not matches_file(config.filter, file_meta):
                    continue

            logger.info("automation.started", name=config.name, trigger=trigger)
            try:
                # Retrieve context
                chunks = await self._retriever.retrieve(config.prompt)
                context = "\n\n".join([c.text for c in chunks])

                # Generate response
                messages = [
                    {"role": "system", "content": "You are an automation assistant."},
                    {"role": "user", "content": f"Context:\n{context}\n\nTask: {config.prompt}"},
                ]
                response = await self._llm.chat(messages)

                # Execute action
                if config.action.type == "execute_sql":
                    # Parse as SQL statements
                    statements = [s.strip() for s in response.split(";") if s.strip()]
                    await self._db_writer.execute_many(statements)

                elif config.action.type == "write_sheet":
                    # Parse as CSV rows
                    f = io.StringIO(response)
                    reader = csv.reader(f)
                    rows = list(reader)
                    if rows:
                        self._sheets_writer.write_rows(config.action.target, config.name, rows)

                elif config.action.type == "notify":
                    logger.info("automation.notify", name=config.name, result=response[:200])

                logger.info("automation.completed", name=config.name)
            except Exception as exc:
                logger.error("automation.failed", name=config.name, error=str(exc))
