"""Vision-Language Model integration for document OCR + KV extraction.

Replaces Tesseract with Llama-3.2-Vision (Ollama) for high-quality text
transcription and structured key-value parsing on scanned documents and
images. The module exposes:

- VisionClient (Protocol) and OllamaVisionClient (httpx implementation).
- VisionExtractor: orchestrates two passes (text then JSON KV) with retries.
- CircuitBreaker: Redis-backed safety net to fall back to Tesseract when
  the VLM is unhealthy.
- prepare_image: Pillow-based downscaler used by the worker before each call.
"""

from __future__ import annotations

from src.vision.circuit_breaker import CircuitBreaker, CircuitState
from src.vision.client import OllamaVisionClient, OpenAICompatVisionClient, VisionClient, VisionTimeoutError
from src.vision.extractor import (
    ExtractedDocumentSchema,
    VisionExtractionResult,
    VisionExtractor,
)
from src.vision.image_utils import prepare_image

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "ExtractedDocumentSchema",
    "OllamaVisionClient",
    "OpenAICompatVisionClient",
    "VisionClient",
    "VisionExtractionResult",
    "VisionExtractor",
    "VisionTimeoutError",
    "prepare_image",
]
