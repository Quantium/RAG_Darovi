"""Tests for src/generator/sheets_writer.py — turns GREEN in Phase 6."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.generator.sheets_writer import SheetsWriter


class TestSheetsWriter:
    @patch("src.generator.sheets_writer.gspread.service_account")
    def test_write_rows_to_sheet(self, mock_gspread):
        mock_sheet = MagicMock()
        mock_gspread.return_value.open_by_key.return_value.worksheet.return_value = mock_sheet
        writer = SheetsWriter(credentials_path="credentials/sa.json")
        writer.write_rows("spreadsheet-id", "Sheet1", [["Alice", "30"], ["Bob", "25"]])
        mock_sheet.append_rows.assert_called_once()

    @patch("src.generator.sheets_writer.gspread.service_account")
    def test_creates_sheet_if_missing(self, mock_gspread):
        mock_spreadsheet = MagicMock()
        mock_spreadsheet.worksheet.side_effect = Exception("not found")
        mock_spreadsheet.add_worksheet.return_value = MagicMock()
        mock_gspread.return_value.open_by_key.return_value = mock_spreadsheet
        writer = SheetsWriter(credentials_path="credentials/sa.json")
        writer.write_rows("spreadsheet-id", "NewSheet", [["data"]])
        mock_spreadsheet.add_worksheet.assert_called_once()
