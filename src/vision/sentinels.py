"""Sentinels exchanged between converters and the vision_extract task.

Converters run synchronously inside the `convert` Celery queue and must NOT
block on the VLM. Instead, they leave a sentinel in the converted text for
each page that needs OCR. The downstream `vision_extract` task scans the
file, replaces sentinels with VLM output and persists structured KV pairs.
"""

from __future__ import annotations

import re

VISION_SENTINEL_TEMPLATE = "\u0000VISION_NEEDED:{page}\u0000"
VISION_SENTINEL_RE = re.compile(r"\u0000VISION_NEEDED:(\d+)\u0000")


def has_sentinels(text: str) -> bool:
    return bool(VISION_SENTINEL_RE.search(text))


def find_pages(text: str) -> list[int]:
    return [int(m.group(1)) for m in VISION_SENTINEL_RE.finditer(text)]
