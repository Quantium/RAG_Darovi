"""Tests for src/converter/pdf_converter.py — turns GREEN in Phase 3."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.converter.pdf_converter import PdfConverter


class TestPdfConverter:
    def test_extract_text_from_pdf(self, sample_pdf_bytes):
        converter = PdfConverter()
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "Hello World"
            mock_page.extract_tables.return_value = []
            mock_open.return_value.__enter__.return_value.pages = [mock_page]
            text = converter.convert(sample_pdf_bytes, "test.pdf", "application/pdf")
            assert "Hello World" in text

    @patch("src.converter.pdf_converter.pytesseract.image_to_string", return_value="OCR text")
    @patch("src.converter.pdf_converter.convert_from_bytes", return_value=[MagicMock()])
    def test_ocr_fallback_on_image_pdf(self, mock_convert, mock_ocr, sample_pdf_bytes):
        converter = PdfConverter()
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = ""
            mock_page.extract_tables.return_value = []
            mock_open.return_value.__enter__.return_value.pages = [mock_page]
            text = converter.convert(sample_pdf_bytes, "scan.pdf", "application/pdf")
            assert "OCR text" in text

    def test_preserves_page_boundaries(self, sample_pdf_bytes):
        converter = PdfConverter()
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            pages = [MagicMock(extract_text=MagicMock(return_value=f"Page {i}"), extract_tables=MagicMock(return_value=[])) for i in range(3)]
            mock_open.return_value.__enter__.return_value.pages = pages
            text = converter.convert(sample_pdf_bytes, "multi.pdf", "application/pdf")
            assert "PAGE" in text

    def test_handles_empty_pdf(self):
        converter = PdfConverter()
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__.return_value.pages = []
            text = converter.convert(b"", "empty.pdf", "application/pdf")
            assert text == ""

    def test_detects_tables(self, sample_pdf_bytes):
        converter = PdfConverter()
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "Some text"
            mock_page.extract_tables.return_value = [
                [["Col1", "Col2"], ["A", "B"]]
            ]
            mock_open.return_value.__enter__.return_value.pages = [mock_page]
            text = converter.convert(sample_pdf_bytes, "table.pdf", "application/pdf")
            assert "Col1" in text
