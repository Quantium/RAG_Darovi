"""Tests for src/vision/extractor.py — VisionExtractor orchestration."""

from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from config.settings import Settings
from src.vision.extractor import (
    ExtractedDocumentSchema,
    VisionExtractionResult,
    VisionExtractor,
)


def _png_bytes(w: int = 100, h: int = 100) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def vision_settings(settings: Settings) -> Settings:
    """Return the default test settings for VisionExtractor tests."""
    return settings


class TestVisionExtractor:
    async def test_extract_text_calls_client_with_text_prompt(self, vision_settings):
        """Verify extract_text calls generate with json_mode=False and returns the response."""
        client = AsyncMock()
        client.generate.return_value = "Page content transcribed"

        extractor = VisionExtractor(client=client, settings=vision_settings)
        text = await extractor.extract_text(_png_bytes())

        assert text == "Page content transcribed"
        client.generate.assert_awaited_once()
        args, kwargs = client.generate.call_args
        assert kwargs.get("json_mode") is False

    async def test_extract_kv_returns_validated_schema(self, vision_settings):
        """Verify extract_kv parses a valid JSON response into a typed ExtractedDocumentSchema."""
        client = AsyncMock()
        payload = {
            "document_type": "invoice",
            "issuer": "ACME Corp",
            "issued_at": "2026-04-15",
            "total_amount": "1234.56",
            "currency": "USD",
            "parties": ["ACME Corp", "Buyer Inc"],
            "extras": {"po_number": "PO-9001"},
        }
        client.generate.return_value = json.dumps(payload)

        extractor = VisionExtractor(client=client, settings=vision_settings)
        result = await extractor.extract_kv(_png_bytes(), full_text="Invoice ACME...")

        assert isinstance(result, ExtractedDocumentSchema)
        assert result.issuer == "ACME Corp"
        assert result.parties == ["ACME Corp", "Buyer Inc"]
        assert result.extras == {"po_number": "PO-9001"}

    async def test_extract_kv_recovers_from_invalid_json_via_fix_pass(self, vision_settings):
        """Verify extract_kv retries with a fix prompt and succeeds on the second JSON response."""
        client = AsyncMock()
        client.generate.side_effect = [
            "this is not json at all",
            json.dumps({"document_type": "letter"}),
        ]

        extractor = VisionExtractor(client=client, settings=vision_settings)
        result = await extractor.extract_kv(_png_bytes(), full_text="Letter...")

        assert isinstance(result, ExtractedDocumentSchema)
        assert result.document_type == "letter"
        assert client.generate.await_count == 2

    async def test_extract_kv_returns_empty_schema_when_fix_also_fails(self, vision_settings):
        """Verify extract_kv returns an empty schema when both the initial and fix passes produce invalid JSON."""
        client = AsyncMock()
        client.generate.side_effect = ["garbage", "still garbage"]

        extractor = VisionExtractor(client=client, settings=vision_settings)
        result = await extractor.extract_kv(_png_bytes(), full_text="ctx")

        assert isinstance(result, ExtractedDocumentSchema)
        assert result.issuer is None
        assert result.extras == {}

    async def test_extract_full_returns_text_and_kv(self, vision_settings):
        """Verify extract() runs both text and KV passes and returns a VisionExtractionResult."""
        client = AsyncMock()
        client.generate.side_effect = [
            "Full transcription of page",
            json.dumps({"document_type": "memo", "issuer": "Director"}),
        ]

        extractor = VisionExtractor(client=client, settings=vision_settings)
        result = await extractor.extract(_png_bytes())

        assert isinstance(result, VisionExtractionResult)
        assert result.text == "Full transcription of page"
        assert result.kv.issuer == "Director"
