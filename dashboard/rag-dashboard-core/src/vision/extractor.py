"""High-level VLM extraction orchestrator.

Two-pass strategy:
1) Free-form OCR (`extract_text`) for the chunker / embedder pipeline.
2) Structured key-value JSON (`extract_kv`) backed by a Pydantic schema so
   downstream Postgres writes are validated and type-safe.

If the model returns malformed JSON, a single text-only "fix the JSON" pass
is attempted (cheaper than rasterizing again). When both attempts fail an
empty schema is returned so the pipeline never crashes on a bad page —
the page text still flows through to Milvus.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from config.settings import Settings
from src.vision.client import VisionClient
from src.vision.image_utils import prepare_image
from src.vision.prompts import EXTRACT_KV_PROMPT, EXTRACT_TEXT_PROMPT, FIX_JSON_PROMPT

logger = structlog.get_logger()

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class ExtractedDocumentSchema(BaseModel):
    """Validated output of the structured KV pass."""

    model_config = ConfigDict(extra="ignore")

    document_type: str | None = None
    issuer: str | None = None
    issued_at: date | None = None
    total_amount: str | None = None
    currency: str | None = None
    parties: list[str] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("issued_at", mode="before")
    @classmethod
    def _parse_date(cls, value: Any) -> date | None:
        """Coerce various date string formats and None-like values to a date object.

        Args:
            value: Raw value from the VLM JSON (string, date, or null-like).

        Returns:
            Parsed date object, or None if the value is empty or unparseable.
        """
        if value in (None, "", "null"):
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue
        return None

    @field_validator("parties", mode="before")
    @classmethod
    def _coerce_parties(cls, value: Any) -> list[str]:
        """Normalize the parties field to a list of strings.

        Args:
            value: Raw value which may be a list, a single string, or None.

        Returns:
            List of non-None string party names.
        """
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        if isinstance(value, str):
            return [value]
        return []

    @field_validator("extras", mode="before")
    @classmethod
    def _coerce_extras(cls, value: Any) -> dict[str, Any]:
        """Normalize the extras field to a dict, returning empty dict for null or non-dict values.

        Args:
            value: Raw value which may be a dict, empty string, or None.

        Returns:
            Dict of extra fields, or an empty dict if the value is unusable.
        """
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return value
        return {}


@dataclass(frozen=True)
class VisionExtractionResult:
    text: str
    kv: ExtractedDocumentSchema


class VisionExtractor:
    """Coordinates text + KV passes around a `VisionClient` implementation."""

    def __init__(self, client: VisionClient, settings: Settings) -> None:
        """Initialize the extractor with a VisionClient and application settings.

        Args:
            client: VisionClient implementation to use for generation calls.
            settings: Application settings providing max image size and other parameters.
        """
        self._client = client
        self._settings = settings

    async def extract(self, image_bytes: bytes) -> VisionExtractionResult:
        """Run both the text OCR and structured KV extraction passes on an image.

        Args:
            image_bytes: Raw image bytes to process.

        Returns:
            VisionExtractionResult containing the OCR text and validated KV schema.
        """
        text = await self.extract_text(image_bytes)
        kv = await self.extract_kv(image_bytes, full_text=text)
        return VisionExtractionResult(text=text, kv=kv)

    async def extract_text(self, image_bytes: bytes) -> str:
        """Run a free-form OCR pass on an image and return the transcribed text.

        Args:
            image_bytes: Raw image bytes to OCR.

        Returns:
            Free-form text transcription produced by the VLM.
        """
        prepared = prepare_image(image_bytes, max_mb=self._settings.vision_max_image_mb)
        b64 = base64.b64encode(prepared).decode()
        return await self._client.generate(EXTRACT_TEXT_PROMPT, b64, json_mode=False)

    async def extract_kv(self, image_bytes: bytes, *, full_text: str) -> ExtractedDocumentSchema:
        """Run a structured key-value extraction pass and return a validated schema.

        Attempts a JSON-fix retry if the first pass returns malformed JSON.
        Returns an empty ExtractedDocumentSchema if both passes fail.

        Args:
            image_bytes: Raw image bytes to analyze.
            full_text: OCR text from extract_text, used to anchor the extraction prompt.

        Returns:
            Validated ExtractedDocumentSchema populated from the VLM response.
        """
        prepared = prepare_image(image_bytes, max_mb=self._settings.vision_max_image_mb)
        b64 = base64.b64encode(prepared).decode()
        prompt = (
            f"{EXTRACT_KV_PROMPT}\n\n"
            f"Document transcription (authoritative for spelling):\n---\n{full_text}\n---"
        )
        raw = await self._client.generate(prompt, b64, json_mode=True)

        parsed = _safe_parse_json(raw)
        if parsed is None:
            logger.warning("vision.extractor.invalid_json", attempt=1)
            fix_prompt = f"{FIX_JSON_PROMPT}{raw}"
            try:
                fix_raw = await self._client.generate(fix_prompt, b64, json_mode=True)
            except Exception as exc:
                logger.warning("vision.extractor.fix_pass_failed", error=str(exc))
                return ExtractedDocumentSchema()
            parsed = _safe_parse_json(fix_raw)
            if parsed is None:
                logger.warning("vision.extractor.invalid_json", attempt=2)
                return ExtractedDocumentSchema()

        try:
            return ExtractedDocumentSchema.model_validate(parsed)
        except ValidationError as exc:
            logger.warning("vision.extractor.schema_validation_failed", error=str(exc))
            return ExtractedDocumentSchema()


def _safe_parse_json(raw: str) -> dict[str, Any] | None:
    """Attempt to parse a JSON object from a raw string, tolerating markdown fences and prose.

    Args:
        raw: Raw string from the VLM that may contain a JSON object.

    Returns:
        Parsed dict if a valid JSON object is found, or None if parsing fails.
    """
    if not raw:
        return None
    candidate = raw.strip()

    fence_match = _JSON_FENCE_RE.search(candidate)
    if fence_match:
        candidate = fence_match.group(1).strip()

    try:
        parsed = json.loads(candidate)
    except (ValueError, TypeError):
        # Some models prepend prose. Try to locate the first JSON object.
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(candidate[start : end + 1])
        except (ValueError, TypeError):
            return None

    if isinstance(parsed, dict):
        return parsed
    return None
