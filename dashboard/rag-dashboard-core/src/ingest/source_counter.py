"""Enumerate source files for dashboard metrics (local folder)."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from config.settings import Settings


def _count_local_files(root: Path) -> int:
    if not root.exists() or not root.is_dir():
        return 0
    n = 0
    for _dirpath, _dirnames, filenames in os.walk(root):
        n += sum(1 for fn in filenames if (Path(_dirpath) / fn).is_file())
    return n


class SourceCounter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def count(self) -> tuple[int | None, str]:
        """Return (file_count_or_none, human-readable source URL)."""
        root = Path(self._settings.local_source_folder or "").expanduser()
        url = root.as_uri() if root.exists() else f"file://{quote(str(root))}"
        return _count_local_files(root), url
