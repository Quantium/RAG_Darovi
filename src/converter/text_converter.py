from __future__ import annotations

import structlog
from bs4 import BeautifulSoup

from src.converter.base import FileConverter

logger = structlog.get_logger()


class TextConverter(FileConverter):
    def convert(self, raw_bytes: bytes, file_name: str, mime_type: str) -> str:
        """Handle text/plain, text/markdown, and text/html."""
        logger.info("converter.text.start", file_name=file_name, mime_type=mime_type)
        
        if not raw_bytes:
            return ""

        try:
            content = raw_bytes.decode("utf-8")
            
            if "text/html" in mime_type:
                soup = BeautifulSoup(content, "html.parser")
                return soup.get_text(separator="\n", strip=True)
            
            # For plain text and markdown, return as is (normalized)
            lines = [line.rstrip() for line in content.splitlines()]
            return "\n".join(lines)
            
        except Exception as e:
            logger.error("converter.text.error", file_name=file_name, error=str(e))
            raise
