from __future__ import annotations

import fnmatch
from typing import Any, Literal

import yaml
from pydantic import BaseModel


class AutomationFilter(BaseModel):
    mime_type: str | None = None
    name_pattern: str | None = None


class AutomationAction(BaseModel):
    type: Literal["execute_sql", "write_sheet", "notify"]
    target: str


class AutomationConfig(BaseModel):
    name: str
    trigger: Literal["on_new_file", "schedule", "manual"]
    filter: AutomationFilter | None = None
    prompt: str
    action: AutomationAction


def parse_automation(yaml_str: str) -> AutomationConfig:
    """Load and validate an automation configuration from YAML."""
    try:
        data = yaml.safe_load(yaml_str)
        if not data:
            raise ValueError("Empty YAML automation configuration.")
        return AutomationConfig(**data)
    except Exception as exc:
        raise ValueError(f"Invalid automation configuration: {str(exc)}")


def matches_file(automation_filter: AutomationFilter, file_meta: dict[str, Any]) -> bool:
    """Return True if the file metadata matches the filter criteria."""
    if not automation_filter:
        return True

    # Check mime type (exact match)
    if automation_filter.mime_type:
        if file_meta.get("mimeType") != automation_filter.mime_type:
            return False

    # Check name pattern (glob/fnmatch)
    if automation_filter.name_pattern:
        if not fnmatch.fnmatch(file_meta.get("name", ""), automation_filter.name_pattern):
            return False

    return True
