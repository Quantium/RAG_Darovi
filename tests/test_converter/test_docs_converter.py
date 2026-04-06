"""Tests for src/converter/docs_converter.py — turns GREEN in Phase 3."""

from __future__ import annotations

from src.converter.docs_converter import DocsConverter


class TestDocsConverter:
    def test_export_google_doc_as_text(self):
        converter = DocsConverter()
        text = converter.convert(b"Hello world", "doc.txt", "text/plain")
        assert "Hello world" in text

    def test_preserves_heading_structure(self):
        converter = DocsConverter()
        raw = b"# Title\n\nParagraph text\n\n## Section\n\nMore text"
        text = converter.convert(raw, "doc.txt", "text/plain")
        assert "# Title" in text
        assert "## Section" in text

    def test_handles_empty_document(self):
        converter = DocsConverter()
        text = converter.convert(b"", "empty.txt", "text/plain")
        assert text == ""
