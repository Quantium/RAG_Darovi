"""Multi-tenancy helpers for retrieval_admin.

The Milvus collection for a licitación is always resolved server-side from the
registry (``public.licitaciones``) by slug — a raw collection name from the client
is never trusted. ``validate_slug`` is the format guard applied before the lookup.
"""

from __future__ import annotations

import re

_SLUG_RE = re.compile(r"^[a-z0-9_]+$")


def validate_slug(slug: str) -> str:
    """Return the slug unchanged if identifier-safe (``[a-z0-9_]+``), else raise ValueError."""
    if not _SLUG_RE.match(slug):
        raise ValueError(f"invalid slug {slug!r}")
    return slug
