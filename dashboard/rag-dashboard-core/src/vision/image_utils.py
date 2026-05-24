"""Image preparation helpers for the VLM pipeline.

Llama-3.2-Vision tolerates large inputs but throughput collapses (and Ollama
can OOM) past a few MB. `prepare_image` is a defensive downscaler invoked
right before every VLM call.
"""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

_MAX_DIMENSION_PX = 2048
_JPEG_QUALITY = 85


def prepare_image(raw_bytes: bytes, *, max_mb: int) -> bytes:
    """Return image bytes within `max_mb`, downscaling/recompressing if needed.

    Idempotent: when the input already fits the budget, the original bytes
    are returned unchanged so callers can short-circuit unchanged uploads.
    """
    if not raw_bytes:
        raise ValueError("prepare_image: empty bytes")

    max_bytes = max_mb * 1024 * 1024
    if len(raw_bytes) <= max_bytes:
        return raw_bytes

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            img.load()
            if img.mode not in {"RGB", "L"}:
                img = img.convert("RGB")

            if max(img.size) > _MAX_DIMENSION_PX:
                ratio = _MAX_DIMENSION_PX / float(max(img.size))
                new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
            return buf.getvalue()
    except UnidentifiedImageError as exc:
        raise ValueError("prepare_image: not a valid image") from exc
