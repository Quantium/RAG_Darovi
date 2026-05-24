from __future__ import annotations

import io
import sys
from pathlib import Path

import openpyxl
from docx import Document

SERVICE_ROOT = Path(__file__).resolve().parents[1]
for module_name in [name for name in list(sys.modules) if name == "app" or name.startswith("app.")]:
    del sys.modules[module_name]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.extractors import IMAGE_SENTINEL, extract_text


def test_extract_text_keeps_markdown_content():
    raw_markdown = b"# Title\n\n> Quoted line\n\n- item"

    extracted = extract_text(raw_markdown, "text/markdown", "sample.md")

    assert "# Title" in extracted
    assert "> Quoted line" in extracted
    assert "- item" in extracted


def test_extract_text_converts_html_to_markdown_table_and_quote():
    raw_html = (
        b"<h1>Report</h1>"
        b"<blockquote>Important note</blockquote>"
        b"<table><tr><th>ColA</th><th>ColB</th></tr><tr><td>1</td><td>2</td></tr></table>"
    )

    extracted = extract_text(raw_html, "text/html", "report.html")

    assert "# Report" in extracted
    assert "> Important note" in extracted
    assert "| ColA | ColB |" in extracted
    assert "| 1 | 2 |" in extracted


def test_extract_text_converts_xlsx_to_markdown_table():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Summary"
    sheet.append(["Name", "Score"])
    sheet.append(["Alice", 10])

    buffer = io.BytesIO()
    workbook.save(buffer)
    raw_xlsx = buffer.getvalue()

    extracted = extract_text(
        raw_xlsx,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "scores.xlsx",
    )

    assert "## Sheet: Summary" in extracted
    assert "| Name | Score |" in extracted
    assert "| Alice | 10 |" in extracted


def test_extract_text_converts_docx_to_markdown_headings_and_paragraphs():
    document = Document()
    document.add_heading("Document title", level=1)
    document.add_paragraph("First paragraph.")
    document.add_paragraph("Second paragraph.")

    buffer = io.BytesIO()
    document.save(buffer)
    raw_docx = buffer.getvalue()

    extracted = extract_text(
        raw_docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc.docx",
    )

    assert "# Document title" in extracted
    assert "First paragraph." in extracted
    assert "Second paragraph." in extracted


def test_extract_text_keeps_image_sentinel():
    extracted = extract_text(b"binary", "image/png", "img.png")

    assert extracted == IMAGE_SENTINEL
