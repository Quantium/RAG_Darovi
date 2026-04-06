from __future__ import annotations

import structlog

from src.converter.base import FileConverter

logger = structlog.get_logger()


class DocsConverter(FileConverter):
    def convert(self, raw_bytes: bytes, file_name: str, mime_type: str) -> str:
        """Process plain text from Google Docs export."""
        logger.info("converter.docs.start", file_name=file_name)

        if not raw_bytes:
            return ""

        try:
            text = raw_bytes.decode("utf-8")
            # Basic normalization: ensure consistent line endings and strip trailing space
            lines = [line.rstrip() for line in text.splitlines()]
            return "\n".join(lines)
        except Exception as e:
            logger.error("converter.docs.error", file_name=file_name, error=str(e))
            raise
