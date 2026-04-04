from __future__ import annotations

import time
from typing import AsyncIterator, Protocol, Any

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

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]: ...


class OpenAICompatibleLLMClient:
    """LLM client for any OpenAI-compatible API (Ollama, Gemini, DeepSeek)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if args and isinstance(args[0], Settings):
            settings = args[0]
            # Use same logic as create_llm_client but inside __init__ for test compatibility
            providers = {
                "ollama": (settings.llm_base_url, "ollama"),
                "gemini": (
                    "https://generativelanguage.googleapis.com/v1beta/openai/",
                    settings.llm_api_key.get_secret_value(),
                ),
                "deepseek": (
                    "https://api.deepseek.com/v1/",
                    settings.llm_api_key.get_secret_value(),
                ),
            }
            if settings.llm_provider not in providers:
                raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
            
            base_url, api_key = providers[settings.llm_provider]
            model = settings.llm_model
        else:
            base_url = kwargs.get("base_url") or (args[0] if len(args) > 0 else None)
            api_key = kwargs.get("api_key") or (args[1] if len(args) > 1 else None)
            model = kwargs.get("model") or (args[2] if len(args) > 2 else None)

        if not base_url or not api_key or not model:
            raise TypeError("OpenAICompatibleLLMClient requires base_url, api_key, and model (or a Settings object)")

        self._client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model
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
                messages=messages,
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
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            async for chunk in stream:
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
            raise ConnectionError(
                f"Circuit breaker open. Retry after {wait_time:.0f}s"
            )

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
