from __future__ import annotations

import asyncio
from typing import Protocol

import httpx
import structlog

from config.settings import Settings

logger = structlog.get_logger()


class VisionError(Exception):
    """Base class for vision-client errors."""


class VisionTimeoutError(VisionError):
    """Raised when the upstream VLM call exceeds `vision_request_timeout_s`."""


class VisionClient(Protocol):
    async def generate(self, prompt: str, image_b64: str, *, json_mode: bool) -> str:
        """Run a single VLM generation. Returns the raw response string."""
        ...


class OpenAICompatVisionClient:
    """VisionClient backed by any OpenAI-compatible chat/completions endpoint."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 3,
        retry_base_s: float = 1.0,
    ) -> None:
        self._base_url = settings.vision_external_base_url.rstrip("/")
        self._api_key = settings.vision_external_api_key
        self._model = settings.vision_external_model
        self._timeout = httpx.Timeout(float(settings.vision_request_timeout_s), connect=10.0)
        self._transport = transport
        self._max_retries = max(1, max_retries)
        self._retry_base_s = retry_base_s

    async def generate(self, prompt: str, image_b64: str, *, json_mode: bool) -> str:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                }
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                async with self._build_client() as client:
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                    if response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"Vision upstream {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                    response.raise_for_status()
                    data = response.json()
                    text = data["choices"][0]["message"]["content"]
                    if not isinstance(text, str):
                        raise VisionError(f"Unexpected response payload: {data!r}")
                    return text
            except httpx.ReadTimeout as exc:
                logger.warning("vision.client.timeout", attempt=attempt + 1, error=str(exc))
                last_exc = VisionTimeoutError(str(exc))
                break
            except (httpx.ConnectError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt + 1 >= self._max_retries:
                    break
                sleep_for = self._retry_base_s * (2**attempt)
                logger.warning("vision.client.retry", attempt=attempt + 1, sleep_for=sleep_for, error=str(exc))
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
            except Exception as exc:
                last_exc = exc
                break

        assert last_exc is not None
        if isinstance(last_exc, VisionTimeoutError):
            raise last_exc
        raise VisionError(str(last_exc)) from last_exc

    def _build_client(self) -> httpx.AsyncClient:
        kwargs: dict[str, object] = {"timeout": self._timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)
