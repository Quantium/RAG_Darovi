from __future__ import annotations

from src.converter.text_converter import TextConverter


class TestTextConverter:
    def test_convert_plain_text(self):
        converter = TextConverter()
        text = converter.convert(b"Hello", "test.txt", "text/plain")
        assert text == "Hello"

    def test_convert_markdown(self):
        converter = TextConverter()
        text = converter.convert(b"# Title\nContent", "test.md", "text/markdown")
        assert "# Title" in text

    def test_convert_html(self):
        converter = TextConverter()
        html = b"<html><body><h1>Title</h1><p>Paragraph</p></body></html>"
        text = converter.convert(html, "test.html", "text/html")
        assert "Title" in text
        assert "Paragraph" in text
        assert "<html>" not in text
