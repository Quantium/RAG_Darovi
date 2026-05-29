"""Tests for src/converter/image_converter.py — emits VLM sentinels."""

from __future__ import annotations

import pytest

from src.converter import get_converter
from src.converter.image_converter import VISION_SENTINEL_TEMPLATE, ImageConverter


class TestImageConverter:
    def test_emits_vision_sentinel(self):
        """Verify image conversion emits a VISION_NEEDED sentinel and a PAGE 1 marker."""
        conv = ImageConverter()
        text = conv.convert(b"\x89PNG\r\n\x1a\n...", "scan.png", "image/png")
        assert VISION_SENTINEL_TEMPLATE.format(page=1) in text
        assert "--- PAGE 1 ---" in text

    def test_handles_empty_bytes(self):
        """Verify empty byte input returns an empty string without raising."""
        conv = ImageConverter()
        assert conv.convert(b"", "blank.png", "image/png") == ""

    @pytest.mark.parametrize(
        "mime",
        ["image/png", "image/jpeg", "image/tiff", "image/webp"],
    )
    def test_registered_for_image_mimes(self, mime):
        """Verify get_converter returns an ImageConverter for common image MIME types."""
        conv = get_converter(mime)
        assert isinstance(conv, ImageConverter)
