from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.converter.docx_converter import DocxConverter


class TestDocxConverter:
    @patch("src.converter.docx_converter.docx.Document")
    def test_convert_docx(self, mock_doc_cls):
        mock_doc = MagicMock()
        mock_para = MagicMock(text="Hello", style=MagicMock(name="Normal"))
        mock_doc.paragraphs = [mock_para]
        mock_doc.tables = []
        mock_doc_cls.return_value = mock_doc

        converter = DocxConverter()
        text = converter.convert(
            b"fake", "test.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert "Hello" in text

    @patch("src.converter.docx_converter.docx.Document")
    def test_convert_docx_with_headings(self, mock_doc_cls):
        mock_doc = MagicMock()
        mock_style = MagicMock()
        mock_style.name = "Heading 1"
        mock_para = MagicMock(text="Title", style=mock_style)
        mock_doc.paragraphs = [mock_para]
        mock_doc.tables = []
        mock_doc_cls.return_value = mock_doc

        converter = DocxConverter()
        text = converter.convert(
            b"fake", "test.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert "# Title" in text
