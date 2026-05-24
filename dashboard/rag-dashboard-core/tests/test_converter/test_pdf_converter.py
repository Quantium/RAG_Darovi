"""Tests for src/converter/pdf_converter.py.

The converter no longer drives Tesseract directly. When `vision_enabled` is
True (default), low-quality pages are marked with a VLM sentinel that is
resolved later in the `vision_extract` Celery task. Tesseract remains
available behind `vision_enabled=False` as a fallback.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from config.settings import Settings
from src.converter.pdf_converter import PdfConverter
from src.vision.sentinels import VISION_SENTINEL_TEMPLATE


def _settings_with_vision(enabled: bool = True) -> Settings:
    return Settings(vision_enabled=enabled)


class TestPdfConverter:
    def test_extract_text_from_pdf(self, sample_pdf_bytes):
        converter = PdfConverter()
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            mock_page = MagicMock()
            # Long enough to clear the text-quality threshold (>= 40 non-ws chars).
            mock_page.extract_text.return_value = (
                "Hello World, this is a paragraph long enough to count as good quality text."
            )
            mock_page.extract_tables.return_value = []
            mock_open.return_value.__enter__.return_value.pages = [mock_page]
            text = converter.convert(sample_pdf_bytes, "test.pdf", "application/pdf")
            assert "Hello World" in text

    def test_low_quality_page_emits_vision_sentinel_when_enabled(self, sample_pdf_bytes):
        converter = PdfConverter(_settings_with_vision(True))
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "L\nA\nI\nC\nN\nE\nD\nI\nF\nN\nO\nC"
            mock_page.extract_tables.return_value = []
            mock_open.return_value.__enter__.return_value.pages = [mock_page]

            text = converter.convert(sample_pdf_bytes, "scan.pdf", "application/pdf")

            assert VISION_SENTINEL_TEMPLATE.format(page=1) in text

    def test_low_quality_page_falls_back_to_tesseract_when_vision_disabled(self, sample_pdf_bytes):
        converter = PdfConverter(_settings_with_vision(False))
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open, patch(
            "src.converter.pdf_converter.convert_from_bytes", return_value=[MagicMock()]
        ), patch("pytesseract.image_to_string", return_value="Recovered OCR text"):
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "L\nA\nI\nC\nN\nE\nD"
            mock_page.extract_tables.return_value = []
            mock_open.return_value.__enter__.return_value.pages = [mock_page]

            text = converter.convert(sample_pdf_bytes, "scan.pdf", "application/pdf")

            assert "Recovered OCR text" in text
            assert VISION_SENTINEL_TEMPLATE.format(page=1) not in text

    def test_does_not_mark_good_quality_pages(self, sample_pdf_bytes):
        converter = PdfConverter(_settings_with_vision(True))
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = (
                "This is a good quality paragraph with enough natural text and structure."
            )
            mock_page.extract_tables.return_value = []
            mock_open.return_value.__enter__.return_value.pages = [mock_page]

            text = converter.convert(sample_pdf_bytes, "good-layer.pdf", "application/pdf")

            assert "good quality paragraph" in text
            assert VISION_SENTINEL_TEMPLATE.format(page=1) not in text

    def test_low_quality_with_tables_still_marks_for_vision(self, sample_pdf_bytes):
        converter = PdfConverter(_settings_with_vision(True))
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "L\nA\nI\nC\nN\nE\nD"
            mock_page.extract_tables.return_value = [[["Col1", "Col2"], ["A", "B"]]]
            mock_open.return_value.__enter__.return_value.pages = [mock_page]

            text = converter.convert(sample_pdf_bytes, "tables-low.pdf", "application/pdf")

            assert VISION_SENTINEL_TEMPLATE.format(page=1) in text
            assert "Col1" in text

    def test_preserves_page_boundaries(self, sample_pdf_bytes):
        converter = PdfConverter()
        with patch("src.converter.pdf_converter.pdfplumber.open") as mock_open:
            pages = [
                MagicMock(extract_text=MagicMock(return_value=f"Page {i}"), extract_tables=MagicMock(return_value=[]))
                for i in range(3)
            ]
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
            mock_page.extract_tables.return_value = [[["Col1", "Col2"], ["A", "B"]]]
            mock_open.return_value.__enter__.return_value.pages = [mock_page]
            text = converter.convert(sample_pdf_bytes, "table.pdf", "application/pdf")
            assert "Col1" in text
