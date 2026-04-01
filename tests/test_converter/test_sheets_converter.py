"""Tests for src/converter/sheets_converter.py — turns GREEN in Phase 3."""
from __future__ import annotations

from src.converter.sheets_converter import SheetsConverter


class TestSheetsConverter:
    def test_export_sheet_as_csv(self):
        converter = SheetsConverter()
        csv_bytes = b"Name,Age\nAlice,30\nBob,25"
        text = converter.convert(csv_bytes, "data.csv", "text/csv")
        assert "Name" in text
        assert "Alice" in text

    def test_handles_multiple_sheets(self):
        converter = SheetsConverter()
        csv_bytes = b"Sheet: Sales\nProduct,Revenue\nA,100\n\nSheet: Costs\nItem,Amount\nX,50"
        text = converter.convert(csv_bytes, "multi.csv", "text/csv")
        assert "Sales" in text or "Costs" in text

    def test_handles_empty_sheet(self):
        converter = SheetsConverter()
        csv_bytes = b"Name,Age"
        text = converter.convert(csv_bytes, "empty.csv", "text/csv")
        assert "Name" in text
