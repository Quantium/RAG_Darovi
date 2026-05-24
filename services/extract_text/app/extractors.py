from __future__ import annotations

import io
import re

from bs4 import BeautifulSoup
from docx import Document
import markdown as md
import openpyxl
import pdfplumber

from .settings import Settings

IMAGE_SENTINEL = "\x00VISION_NEEDED:1\x00"
VISION_SENTINEL_TEMPLATE = "\x00VISION_NEEDED:{page}\x00"


def has_sentinels(text: str) -> bool:
    return "\x00VISION_NEEDED:" in text


def _page_quality_ok(text: str, settings: Settings) -> bool:
    non_ws = len(re.findall(r"\S", text))
    if non_ws < settings.ocr_min_text_chars:
        return False
    alpha = len(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", text))
    if non_ws and alpha / non_ws < settings.ocr_min_alpha_ratio:
        return False
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        single_char = sum(1 for ln in lines if len(ln) == 1)
        if single_char / len(lines) > settings.ocr_max_single_char_line_ratio:
            return False
    return True


def extract_text(raw_bytes: bytes, mime_type: str, file_name: str, settings: Settings | None = None) -> str:
    _settings = settings or Settings()
    if mime_type.startswith("image/"):
        return IMAGE_SENTINEL
    if mime_type == "application/pdf":
        return _normalize_markdown(_extract_pdf(raw_bytes, _settings))
    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _extract_docx(raw_bytes)
    if mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return _extract_xlsx(raw_bytes)
    if mime_type == "text/html":
        return _extract_html_as_markdown(raw_bytes)
    if mime_type == "text/markdown":
        return _normalize_markdown(raw_bytes.decode("utf-8", errors="replace"))
    if mime_type in {
        "text/plain",
        "text/csv",
        "application/vnd.google-apps.document",
        "application/vnd.google-apps.spreadsheet",
    }:
        return _normalize_markdown(raw_bytes.decode("utf-8", errors="replace"))
    return _normalize_markdown(raw_bytes.decode("utf-8", errors="replace"))


def _extract_pdf(raw_bytes: bytes, settings: Settings) -> str:
    chunks: list[str] = []
    with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
        for i, page in enumerate(pdf.pages):
            page_num = i + 1
            page_text = page.extract_text() or ""
            if settings.vision_enabled and not _page_quality_ok(page_text, settings):
                chunks.append(VISION_SENTINEL_TEMPLATE.format(page=page_num))
            else:
                chunks.append(page_text)
    return "\n\n".join(chunks)


def _extract_docx(raw_bytes: bytes) -> str:
    doc = Document(io.BytesIO(raw_bytes))
    lines: list[str] = []
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = paragraph.style.name if paragraph.style is not None else ""
        if style_name.startswith("Heading"):
            heading_level = _parse_heading_level(style_name)
            lines.append(f"{'#' * heading_level} {text}")
            continue
        if style_name.lower().startswith("list"):
            lines.append(f"- {text}")
            continue
        lines.append(text)
    return _normalize_markdown("\n\n".join(lines))


def _extract_xlsx(raw_bytes: bytes) -> str:
    workbook = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
    sections: list[str] = []
    for sheet in workbook.worksheets:
        rows: list[list[str]] = []
        for row in sheet.iter_rows(values_only=True):
            values = ["" if value is None else str(value) for value in row]
            if not any(values):
                continue
            rows.append(values)
        if not rows:
            continue
        section_lines: list[str] = [f"## Sheet: {sheet.title}"]
        section_lines.extend(_rows_to_markdown_table(rows))
        sections.append("\n".join(section_lines))
    return _normalize_markdown("\n\n".join(sections))


def _extract_html_as_markdown(raw_bytes: bytes) -> str:
    soup = BeautifulSoup(raw_bytes.decode("utf-8", errors="replace"), "html.parser")
    chunks: list[str] = []
    root = soup.body if soup.body else soup
    for node in root.find_all(recursive=False):
        markdown_chunk = _html_node_to_markdown(node)
        if markdown_chunk:
            chunks.append(markdown_chunk)
    if not chunks:
        html = md.markdown(raw_bytes.decode("utf-8", errors="replace"))
        return _normalize_markdown(BeautifulSoup(html, "html.parser").get_text("\n"))
    return _normalize_markdown("\n\n".join(chunks))


def _html_node_to_markdown(node) -> str:  # type: ignore[no-untyped-def]
    name = getattr(node, "name", None)
    text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else str(node).strip()
    if not text and name != "table":
        return ""

    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        level = int(name[1])
        return f"{'#' * level} {text}"
    if name == "blockquote":
        quoted_lines = [line.strip() for line in node.get_text("\n", strip=True).splitlines() if line.strip()]
        return "\n".join(f"> {line}" for line in quoted_lines)
    if name in {"ul", "ol"}:
        items = [li.get_text(" ", strip=True) for li in node.find_all("li", recursive=False)]
        return "\n".join(f"- {item}" for item in items if item)
    if name == "table":
        rows: list[list[str]] = []
        for row in node.find_all("tr"):
            cells = row.find_all(["th", "td"])
            row_values = [cell.get_text(" ", strip=True) for cell in cells]
            if any(row_values):
                rows.append(row_values)
        return "\n".join(_rows_to_markdown_table(rows))
    return text


def _rows_to_markdown_table(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []

    width = max(len(row) for row in rows)

    def normalize_row(row: list[str]) -> list[str]:
        return [value.replace("|", r"\|").strip() for value in row] + [""] * (width - len(row))

    normalized_rows = [normalize_row(row) for row in rows]
    header = normalized_rows[0]
    separator = ["---"] * width
    data_rows = normalized_rows[1:]

    output = [
        f"| {' | '.join(header)} |",
        f"| {' | '.join(separator)} |",
    ]
    output.extend(f"| {' | '.join(row)} |" for row in data_rows)
    return output


def _parse_heading_level(style_name: str) -> int:
    match = re.search(r"(\d+)$", style_name)
    if not match:
        return 1
    return max(1, min(int(match.group(1)), 6))


def _normalize_markdown(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized
