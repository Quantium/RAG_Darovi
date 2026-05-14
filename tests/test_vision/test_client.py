"""Tests for src/vision/client.py — OllamaVisionClient httpx wrapper."""

from __future__ import annotations

import base64

import httpx
import pytest

from config.settings import Settings
from src.vision.client import OllamaVisionClient, VisionTimeoutError


@pytest.fixture
def vision_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "vision_base_url": "http://vision-mock:11434",
            "vision_model": "llama3.2-vision:11b",
            "vision_request_timeout_s": 30,
        }
    )


class TestOllamaVisionClient:
    async def test_generate_posts_to_ollama_generate_endpoint(self, vision_settings):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["json"] = request.read()
            return httpx.Response(200, json={"response": "Hello from VLM"})

        transport = httpx.MockTransport(handler)
        client = OllamaVisionClient(vision_settings, transport=transport)

        b64 = base64.b64encode(b"fake-image-bytes").decode()
        result = await client.generate("Describe", b64, json_mode=False)

        assert result == "Hello from VLM"
        assert captured["url"] == "http://vision-mock:11434/api/generate"
        body = captured["json"].decode()
        assert "llama3.2-vision:11b" in body
        assert b64 in body

    async def test_generate_with_json_mode_sets_format(self, vision_settings):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = request.read().decode()
            return httpx.Response(200, json={"response": '{"key": "value"}'})

        transport = httpx.MockTransport(handler)
        client = OllamaVisionClient(vision_settings, transport=transport)

        await client.generate("Extract KV", "Zm9v", json_mode=True)

        assert '"format": "json"' in captured["json"] or '"format":"json"' in captured["json"]

    async def test_generate_raises_vision_timeout_on_read_timeout(self, vision_settings):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("simulated", request=request)

        transport = httpx.MockTransport(handler)
        client = OllamaVisionClient(vision_settings, transport=transport, max_retries=1)

        with pytest.raises(VisionTimeoutError):
            await client.generate("prompt", "Zm9v", json_mode=False)

    async def test_generate_retries_then_succeeds(self, vision_settings):
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            if calls["count"] < 2:
                return httpx.Response(503, json={"error": "busy"})
            return httpx.Response(200, json={"response": "ok"})

        transport = httpx.MockTransport(handler)
        client = OllamaVisionClient(vision_settings, transport=transport, max_retries=3, retry_base_s=0)

        result = await client.generate("prompt", "Zm9v", json_mode=False)
        assert result == "ok"
        assert calls["count"] == 2
