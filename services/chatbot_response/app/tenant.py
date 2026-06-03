"""Multi-tenancy helpers for chatbot_response.

A chat is always scoped to a licitación: its slug namespaces the Redis conversation
history and selects the PostgreSQL schema where ``chat_interactions`` is written. Both
the slug and the schema name come from the registry (``public.licitaciones``); these
validators are the format guards applied before either is used to build a key or a
``SET search_path`` statement (identifiers cannot be parameterized).
"""

from __future__ import annotations

import re

_SLUG_RE = re.compile(r"^[a-z0-9_]+$")
_SCHEMA_RE = re.compile(r"^(public|lic_[a-z0-9_]+)$")


def validate_slug(slug: str) -> str:
    """Return the slug unchanged if identifier-safe (``[a-z0-9_]+``), else raise ValueError."""
    if not _SLUG_RE.match(slug):
        raise ValueError(f"invalid slug {slug!r}")
    return slug


def validate_schema_name(schema_name: str) -> str:
    """Return the schema name if it is ``public`` or ``lic_<slug>``, else raise ValueError."""
    if not _SCHEMA_RE.match(schema_name):
        raise ValueError(f"invalid schema name {schema_name!r}")
    return schema_name
