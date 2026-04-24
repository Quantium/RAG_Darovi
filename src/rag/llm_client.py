from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any, Protocol, cast

import openai
import structlog

from config.settings import Settings

logger = structlog.get_logger()


class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> str: ...

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]: ...


class OpenAICompatibleLLMClient:
    """LLM client for any OpenAI-compatible API (Ollama, Gemini, DeepSeek)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        resolved_base: str | None = None
        resolved_key: str | None = None
        resolved_model: str | None = None
        if args and isinstance(args[0], Settings):
            settings = args[0]
            # Use same provider-resolution logic here for test compatibility.
            if settings.llm_provider == "ollama":
                resolved_base = settings.llm_base_url
                resolved_key = "ollama"
            elif settings.llm_provider == "gemini":
                resolved_base = "https://generativelanguage.googleapis.com/v1beta/openai/"
                resolved_key = settings.llm_api_key.get_secret_value()
            elif settings.llm_provider == "deepseek":
                resolved_base = settings.deepseek_base_url
                resolved_key = settings.deepseek_api_key.get_secret_value() or settings.llm_api_key.get_secret_value()
            else:
                raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
            resolved_model = settings.llm_model
        else:
            raw_base = kwargs.get("base_url") or (args[0] if len(args) > 0 else None)
            raw_key = kwargs.get("api_key") or (args[1] if len(args) > 1 else None)
            raw_model = kwargs.get("model") or (args[2] if len(args) > 2 else None)
            resolved_base = str(raw_base) if raw_base is not None else None
            resolved_key = str(raw_key) if raw_key is not None else None
            resolved_model = str(raw_model) if raw_model is not None else None

        if not resolved_base or not resolved_key or not resolved_model:
            raise TypeError("OpenAICompatibleLLMClient requires base_url, api_key, and model (or a Settings object)")

        self._client = openai.AsyncOpenAI(base_url=resolved_base, api_key=resolved_key)
        self._model = resolved_model
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> str:
        self._check_circuit()
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=cast(Any, messages),
                max_tokens=max_tokens,
                temperature=temperature,
            )
            self._consecutive_failures = 0
            return response.choices[0].message.content or ""
        except Exception as exc:
            self._record_failure()
            logger.error("llm.chat_failed", error=str(exc))
            raise

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        self._check_circuit()
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=cast(Any, messages),
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            async for chunk in cast(AsyncIterator[Any], stream):
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    self._consecutive_failures = 0
                    yield delta
        except Exception as exc:
            self._record_failure()
            logger.error("llm.chat_stream_failed", error=str(exc))
            raise

    def _check_circuit(self) -> None:
        if self._consecutive_failures >= 3 and time.time() < self._circuit_open_until:
            wait_time = self._circuit_open_until - time.time()
            raise ConnectionError(f"Circuit breaker open. Retry after {wait_time:.0f}s")

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            self._circuit_open_until = time.time() + 60.0
            logger.warning("llm.circuit_open", failures=self._consecutive_failures, cooldown=60)


def create_llm_client(settings: Settings) -> OpenAICompatibleLLMClient:
    """Build the LLM client from settings. Provider determines base_url and api_key."""
    return OpenAICompatibleLLMClient(settings)


# Backward compatibility aliases for tests
OllamaLLMClient = OpenAICompatibleLLMClient
GeminiLLMClient = OpenAICompatibleLLMClient
DeepSeekLLMClient = OpenAICompatibleLLMClient
