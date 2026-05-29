"""Page rasterization helpers used by the vision_extract task.

Decouples worker code from pdf2image/Pillow specifics. PDFs are rasterized
one page at a time (pdf2image -> PIL -> PNG bytes). For pure image inputs
(`image/png`, `image/jpeg`, ...) the original bytes are returned unchanged
since they are already a single rasterized page.
"""

from __future__ import annotations

import io

import structlog
from pdf2image import convert_from_bytes
from PIL import Image

logger = structlog.get_logger()


def is_image_mime(mime_type: str) -> bool:
    """Return True if the MIME type represents a raster image format.

    Args:
        mime_type: MIME type string to check.

    Returns:
        True if the type starts with 'image/', False otherwise.
    """
    return mime_type.startswith("image/")


def rasterize_page(raw_bytes: bytes, mime_type: str, page_num: int, *, dpi: int) -> bytes:
    """Return PNG-encoded bytes for the requested page."""
    if is_image_mime(mime_type):
        if page_num != 1:
            raise ValueError(f"Image input only has page 1, got {page_num}")
        return raw_bytes

    if mime_type != "application/pdf":
        raise ValueError(f"Unsupported mime for rasterization: {mime_type}")

    images = convert_from_bytes(raw_bytes, first_page=page_num, last_page=page_num, dpi=dpi)
    if not images:
        raise ValueError(f"Could not rasterize PDF page {page_num}")
    img: Image.Image = images[0]
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
