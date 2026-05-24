"""Image-only converter that defers OCR to the VLM stage.

PNG/JPEG/TIFF/WEBP files are treated as a single page. The sync `convert`
queue must stay fast (Tesseract free), so this converter only emits a
single sentinel marker. The `vision_extract` Celery task picks it up,
fetches the original bytes from MinIO and runs Llama-3.2-Vision.
"""

from __future__ import annotations

import structlog

from src.converter.base import FileConverter  # noqa: F401  (Protocol contract)
from src.vision.sentinels import VISION_SENTINEL_TEMPLATE

logger = structlog.get_logger()


class ImageConverter:
    def convert(self, raw_bytes: bytes, file_name: str, mime_type: str) -> str:
        if not raw_bytes:
            logger.info("converter.image.empty", file_name=file_name, mime_type=mime_type)
            return ""
        logger.info(
            "converter.image.deferred_to_vision",
            file_name=file_name,
            mime_type=mime_type,
            bytes=len(raw_bytes),
        )
        page_marker = VISION_SENTINEL_TEMPLATE.format(page=1)
        return f"--- PAGE 1 ---\n\n{page_marker}"
