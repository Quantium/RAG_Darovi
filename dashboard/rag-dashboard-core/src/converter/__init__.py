from __future__ import annotations

import structlog

from src.converter.base import FileConverter
from src.converter.docx_converter import DocxConverter
from src.converter.image_converter import ImageConverter
from src.converter.pdf_converter import PdfConverter
from src.converter.sheets_converter import SheetsConverter
from src.converter.text_converter import TextConverter
from src.converter.xlsx_converter import XlsxConverter

logger = structlog.get_logger()

_CONVERTERS: dict[str, type[FileConverter]] = {
    "application/pdf": PdfConverter,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxConverter,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": XlsxConverter,
    "text/plain": TextConverter,
    "text/markdown": TextConverter,
    "text/html": TextConverter,
    "text/csv": SheetsConverter,
    "image/png": ImageConverter,
    "image/jpeg": ImageConverter,
    "image/jpg": ImageConverter,
    "image/tiff": ImageConverter,
    "image/webp": ImageConverter,
}


def get_converter(mime_type: str) -> FileConverter:
    """Return the appropriate converter for the given MIME type.

    Logs a warning and raises ValueError for unsupported types.
    """
    converter_cls = _CONVERTERS.get(mime_type)
    if converter_cls is None:
        logger.warning("converter.unsupported_mime_type", mime_type=mime_type)
        raise ValueError(f"No converter registered for MIME type: {mime_type}")
    return converter_cls()
