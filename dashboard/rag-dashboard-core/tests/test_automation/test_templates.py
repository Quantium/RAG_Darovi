"""Tests for src/automation/templates.py — turns GREEN in Phase 6."""

from __future__ import annotations

import pytest

from src.automation.templates import parse_automation, matches_file, AutomationConfig


class TestAutomationTemplates:
    def test_parse_valid_yaml(self):
        """Verify parse_automation returns a valid AutomationConfig from a complete YAML string."""
        yaml_str = """
name: invoice-extractor
trigger: on_new_file
filter:
  mime_type: application/pdf
  name_pattern: "invoice_*"
prompt: "Extract line items."
action:
  type: execute_sql
  target: postgres
"""
        config = parse_automation(yaml_str)
        assert isinstance(config, AutomationConfig)
        assert config.name == "invoice-extractor"

    def test_parse_invalid_yaml(self):
        """Verify parse_automation raises ValueError when required fields are missing."""
        yaml_str = "name: missing-fields"
        with pytest.raises(ValueError):
            parse_automation(yaml_str)

    def test_filter_matches_file(self):
        """Verify matches_file returns True for a matching MIME+name combo and False otherwise."""
        from src.automation.templates import AutomationFilter

        f = AutomationFilter(mime_type="application/pdf", name_pattern="invoice_*")
        assert matches_file(f, {"mimeType": "application/pdf", "name": "invoice_001.pdf"}) is True
        assert matches_file(f, {"mimeType": "text/plain", "name": "readme.txt"}) is False
