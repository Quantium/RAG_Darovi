"""Tests for src/vision/image_utils.py — Pillow-based prepare_image."""

from __future__ import annotations

import io
import os

import pytest
from PIL import Image

from src.vision.image_utils import prepare_image


def _solid_png(width: int, height: int, color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _noisy_png(width: int, height: int) -> bytes:
    """Random pixel data — incompressible, used to exceed the size budget."""
    img = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestPrepareImage:
    def test_passthrough_when_under_limit(self):
        original = _solid_png(800, 600)
        result = prepare_image(original, max_mb=8)
        assert result == original

    def test_downscale_when_over_limit(self):
        large = _noisy_png(3000, 3000)
        assert len(large) > 1 * 1024 * 1024
        result = prepare_image(large, max_mb=1)

        with Image.open(io.BytesIO(result)) as img:
            assert max(img.size) <= 2048

    def test_downscale_returns_jpeg_with_smaller_size(self):
        large = _noisy_png(3000, 3000)
        result = prepare_image(large, max_mb=1)

        assert len(result) < len(large)
        with Image.open(io.BytesIO(result)) as img:
            assert img.format == "JPEG"

    def test_invalid_bytes_raises(self):
        # Larger than max_mb so we force the decode path; truly invalid payload.
        garbage = b"not-an-image" * 200_000
        with pytest.raises(ValueError):
            prepare_image(garbage, max_mb=1)

    def test_empty_bytes_raises(self):
        with pytest.raises(ValueError):
            prepare_image(b"", max_mb=8)
