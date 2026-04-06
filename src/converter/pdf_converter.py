from __future__ import annotations

import io

import pdfplumber
import pytesseract
import structlog
from pdf2image import convert_from_bytes

from src.converter.base import FileConverter

logger = structlog.get_logger()


class PdfConverter(FileConverter):
    def convert(self, raw_bytes: bytes, file_name: str, mime_type: str) -> str:
        """Convert PDF bytes to plain text with OCR fallback and table extraction."""
        logger.info("converter.pdf.start", file_name=file_name)

        if not raw_bytes:
            return ""

        output = []
        try:
            with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
                for i, page in enumerate(pdf.pages):
                    page_num = i + 1
                    page_text = page.extract_text() or ""

                    # Extract tables and format as basic markdown
                    tables = page.extract_tables()
                    table_texts = []
                    if tables:
                        for table in tables:
                            table_texts.append(self._format_table(table))

                    # If no text extracted, try OCR
                    if not page_text.strip() and not tables:
                        logger.debug("converter.pdf.ocr_fallback", page=page_num, file_name=file_name)
                        page_text = self._ocr_page(raw_bytes, page_num)

                    page_content = f"--- PAGE {page_num} ---\n\n{page_text}"
                    if table_texts:
                        page_content += "\n\n" + "\n\n".join(table_texts)

                    output.append(page_content)
        except Exception as e:
            logger.error("converter.pdf.error", file_name=file_name, error=str(e))
            raise

        return "\n\n".join(output)

    def _format_table(self, table: list[list[str | None]]) -> str:
        """Simple markdown table formatting."""
        if not table:
            return ""

        lines = []
        for i, row in enumerate(table):
            # Clean none values
            clean_row = [str(cell) if cell is not None else "" for cell in row]
            lines.append("| " + " | ".join(clean_row) + " |")
            if i == 0:  # Header separator
                lines.append("| " + " | ".join(["---"] * len(clean_row)) + " |")

        return "\n".join(lines)

    def _ocr_page(self, raw_bytes: bytes, page_num: int) -> str:
        """Fall back to OCR for a specific page."""
        try:
            images = convert_from_bytes(raw_bytes, first_page=page_num, last_page=page_num)
            if not images:
                return ""
            return pytesseract.image_to_string(images[0])
        except Exception as e:
            logger.warning("converter.pdf.ocr_failed", page=page_num, error=str(e))
            return ""
