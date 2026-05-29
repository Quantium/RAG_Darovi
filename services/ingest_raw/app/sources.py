from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .settings import Settings


@dataclass
class SourceFile:
    file_id: str
    name: str
    mime_type: str
    source_version: str
    path_hint: str | None = None


class SourceAdapter(Protocol):
    def iter_pages(self, page_size: int) -> Iterator[list[SourceFile]]: ...
    def download_file(self, source_file: SourceFile) -> bytes: ...


class LocalSourceAdapter:
    def __init__(self, settings: Settings) -> None:
        """Initialize the adapter with the local source folder path from settings.

        Args:
            settings: Application settings providing the local_source_folder path.
        """
        self._root = Path(settings.local_source_folder)

    def iter_pages(self, page_size: int) -> Iterator[list[SourceFile]]:
        """Yield pages of SourceFile descriptors discovered recursively under the root folder.

        Args:
            page_size: Maximum number of files per yielded page.

        Yields:
            Lists of SourceFile instances, each page containing at most page_size files.
        """
        if not self._root.exists():
            return
        all_files: list[SourceFile] = []
        for path in self._root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(self._root))
            stat = path.stat()
            file_id = hashlib.sha1(rel.encode("utf-8")).hexdigest()
            mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            all_files.append(
                SourceFile(
                    file_id=file_id,
                    name=path.name,
                    mime_type=mime_type,
                    source_version=f"{stat.st_mtime_ns}:{stat.st_size}",
                    path_hint=rel,
                )
            )
        for offset in range(0, max(len(all_files), 1), page_size):
            page = all_files[offset : offset + page_size]
            if page:
                yield page

    def download_file(self, source_file: SourceFile) -> bytes:
        """Read the raw bytes of a source file from the local filesystem.

        Uses path_hint for a fast direct lookup, then falls back to a full tree search by file ID.

        Args:
            source_file: SourceFile descriptor whose path_hint or file_id is used to locate the file.

        Returns:
            Raw file content as bytes.

        Raises:
            FileNotFoundError: If the file cannot be located under the root folder.
        """
        if source_file.path_hint:
            candidate = self._root / source_file.path_hint
            if candidate.exists():
                return candidate.read_bytes()
        for path in self._root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(self._root))
            if hashlib.sha1(rel.encode("utf-8")).hexdigest() == source_file.file_id:
                return path.read_bytes()
        raise FileNotFoundError(f"Local source file not found for id={source_file.file_id}")


def build_source_adapter(settings: Settings) -> SourceAdapter:
    """Construct the appropriate SourceAdapter based on the configured ingest source.

    Args:
        settings: Application settings providing the ingest_source and related config.

    Returns:
        A SourceAdapter instance ready to list and download source files.
    """
    return LocalSourceAdapter(settings)
