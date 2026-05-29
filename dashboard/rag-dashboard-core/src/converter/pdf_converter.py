from __future__ import annotations

import io

import pdfplumber
import structlog
from pdf2image import convert_from_bytes

from config.settings import Settings
from src.converter.base import FileConverter
from src.converter.text_quality import evaluate_text_quality
from src.vision.sentinels import VISION_SENTINEL_TEMPLATE

logger = structlog.get_logger()


class PdfConverter(FileConverter):
    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the PDF converter with OCR and vision settings.

        Args:
            settings: Optional application settings; defaults to a fresh Settings() if not provided.
        """
        self._settings = settings or Settings()

    def convert(self, raw_bytes: bytes, file_name: str, mime_type: str) -> str:
        """Convert PDF bytes to plain text with OCR fallback and table extraction."""
        logger.info("converter.pdf.start", file_name=file_name)

        if not raw_bytes:
            return ""

        output = []
        pages_total = 0
        vision_marked_pages = 0
        ocr_attempted_pages = 0
        ocr_applied_pages = 0
        ocr_failed_pages = 0
        try:
            with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
                for i, page in enumerate(pdf.pages):
                    page_num = i + 1
                    pages_total += 1
                    page_text = page.extract_text() or ""

                    # Extract tables and format as basic markdown
                    tables = page.extract_tables()
                    table_texts = []
                    if tables:
                        for table in tables:
                            table_texts.append(self._format_table(table))

                    quality = evaluate_text_quality(
                        page_text,
                        min_text_chars=self._settings.ocr_min_text_chars,
                        min_alpha_ratio=self._settings.ocr_min_alpha_ratio,
                        max_single_char_line_ratio=self._settings.ocr_max_single_char_line_ratio,
                    )
                    should_recover = not quality.is_usable
                    fallback_reason = quality.reason
                    logger.debug(
                        "converter.pdf.page_decision",
                        file_name=file_name,
                        page=page_num,
                        tables_count=len(tables),
                        should_recover=should_recover,
                        fallback_reason=fallback_reason,
                        non_ws_chars=quality.non_ws_chars,
                        alpha_ratio=round(quality.alpha_ratio, 4),
                        single_char_line_ratio=round(quality.single_char_line_ratio, 4),
                    )

                    if should_recover:
                        if self._settings.vision_enabled:
                            page_text = VISION_SENTINEL_TEMPLATE.format(page=page_num)
                            vision_marked_pages += 1
                            logger.debug(
                                "converter.pdf.vision_marked",
                                page=page_num,
                                file_name=file_name,
                                fallback_reason=fallback_reason,
                            )
                        else:
                            ocr_attempted_pages += 1
                            ocr_text = self._ocr_page_tesseract(raw_bytes, page_num)
                            if ocr_text.strip():
                                ocr_applied_pages += 1
                                page_text = ocr_text
                            else:
                                ocr_failed_pages += 1

                    page_content = f"--- PAGE {page_num} ---\n\n{page_text}"
                    if table_texts:
                        page_content += "\n\n" + "\n\n".join(table_texts)

                    output.append(page_content)
        except Exception as e:
            logger.error("converter.pdf.error", file_name=file_name, error=str(e))
            raise

        logger.info(
            "converter.pdf.summary",
            file_name=file_name,
            pages_total=pages_total,
            vision_marked_pages=vision_marked_pages,
            ocr_attempted_pages=ocr_attempted_pages,
            ocr_applied_pages=ocr_applied_pages,
            ocr_failed_pages=ocr_failed_pages,
        )
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

    def _ocr_page_tesseract(self, raw_bytes: bytes, page_num: int) -> str:
        """Legacy Tesseract fallback for a specific page.

        Used only when `vision_enabled` is False (or invoked from the
        vision_extract task when the circuit breaker is open). Tesseract
        and pytesseract remain installed in the worker image as a safety
        net for VLM outages — see the migration plan, section 3.6.
        """
        try:
            import pytesseract

            images = convert_from_bytes(
                raw_bytes,
                first_page=page_num,
                last_page=page_num,
                dpi=self._settings.ocr_dpi,
            )
            if not images:
                return ""
            kwargs: dict[str, str] = {}
            if self._settings.ocr_language:
                kwargs["lang"] = self._settings.ocr_language
            if self._settings.ocr_psm:
                kwargs["config"] = f"--psm {self._settings.ocr_psm}"
            return pytesseract.image_to_string(images[0], **kwargs)
        except Exception as e:
            logger.warning("converter.pdf.tesseract_failed", page=page_num, error=str(e))
            return ""
