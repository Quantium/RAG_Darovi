from __future__ import annotations

from typing import Protocol


class FileConverter(Protocol):
    def convert(self, raw_bytes: bytes, file_name: str, mime_type: str) -> str:
        """Convert raw file bytes to plain text."""
        ...
