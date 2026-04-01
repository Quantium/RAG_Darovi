from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.converter.xlsx_converter import XlsxConverter


class TestXlsxConverter:
    @patch("src.converter.xlsx_converter.openpyxl.load_workbook")
    def test_convert_xlsx(self, mock_load):
        mock_wb = MagicMock()
        mock_sheet = MagicMock(title="Sheet1")
        mock_sheet.iter_rows.return_value = [("Header",), ("Value",)]
        mock_wb.worksheets = [mock_sheet]
        mock_load.return_value = mock_wb
        
        converter = XlsxConverter()
        text = converter.convert(b"fake", "test.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        assert "Sheet1" in text
        assert "Header" in text
        assert "Value" in text
