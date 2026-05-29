"""Tests for src/rag/llm_client.py — turns GREEN in Phase 6."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pydantic import SecretStr

from src.rag.llm_client import create_llm_client, OllamaLLMClient, GeminiLLMClient, DeepSeekLLMClient


class TestLLMClient:
    @patch("src.rag.llm_client.openai.AsyncOpenAI")
    async def test_chat_completion_ollama(self, mock_openai, settings):
        """Verify the Ollama LLM client returns a string response from a mocked completion."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Hello!"))]
        )
        mock_openai.return_value = mock_client
        llm = OllamaLLMClient(settings)
        response = await llm.chat([{"role": "user", "content": "Hi"}])
        assert isinstance(response, str)

    @patch("src.rag.llm_client.openai.AsyncOpenAI")
    async def test_chat_completion_gemini(self, mock_openai, settings):
        """Verify the Gemini LLM client returns a string response from a mocked completion."""
        settings_gemini = settings.model_copy(update={"llm_provider": "gemini", "llm_api_key": SecretStr("key")})
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Gemini response"))]
        )
        mock_openai.return_value = mock_client
        llm = GeminiLLMClient(settings_gemini)
        response = await llm.chat([{"role": "user", "content": "Hi"}])
        assert isinstance(response, str)

    @patch("src.rag.llm_client.openai.AsyncOpenAI")
    async def test_chat_completion_deepseek(self, mock_openai, settings):
        """Verify the DeepSeek LLM client returns a string response from a mocked completion."""
        settings_ds = settings.model_copy(update={"llm_provider": "deepseek", "llm_api_key": SecretStr("key")})
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="DeepSeek response"))]
        )
        mock_openai.return_value = mock_client
        llm = DeepSeekLLMClient(settings_ds)
        response = await llm.chat([{"role": "user", "content": "Hi"}])
        assert isinstance(response, str)

    @patch("src.rag.llm_client.openai.AsyncOpenAI")
    async def test_deepseek_uses_dedicated_env_key(self, mock_openai, settings):
        """Verify DeepSeek prefers DEEPSEEK_API_KEY over LLM_API_KEY when both are set."""
        settings_ds = settings.model_copy(
            update={
                "llm_provider": "deepseek",
                "llm_api_key": SecretStr(""),
                "deepseek_api_key": SecretStr("deepseek-secret"),
            }
        )
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="DeepSeek response"))]
        )
        mock_openai.return_value = mock_client

        llm = DeepSeekLLMClient(settings_ds)
        await llm.chat([{"role": "user", "content": "Hi"}])

        _, kwargs = mock_openai.call_args
        assert kwargs["api_key"] == "deepseek-secret"
        assert kwargs["base_url"] == "https://api.deepseek.com/v1/"

    def test_provider_selection_from_config(self, settings):
        """Verify create_llm_client returns an OllamaLLMClient for the default settings provider."""
        llm = create_llm_client(settings)
        assert isinstance(llm, OllamaLLMClient)

    @patch("src.rag.llm_client.openai.AsyncOpenAI")
    async def test_streaming_response(self, mock_openai, settings):
        """Verify chat_stream is an async iterable that can be consumed without errors."""
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        llm = OllamaLLMClient(settings)
        chunks = []
        async for chunk in llm.chat_stream([{"role": "user", "content": "Hi"}]):
            chunks.append(chunk)
        # Should yield at least something or be iterable

    @patch("src.rag.llm_client.openai.AsyncOpenAI")
    async def test_handles_api_error(self, mock_openai, settings):
        """Verify the LLM client propagates API exceptions to the caller."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        mock_openai.return_value = mock_client
        llm = OllamaLLMClient(settings)
        with pytest.raises(Exception, match="API Error"):
            await llm.chat([{"role": "user", "content": "Hi"}])

    @patch("src.rag.llm_client.openai.AsyncOpenAI")
    async def test_respects_max_tokens(self, mock_openai, settings):
        """Verify the max_tokens argument is forwarded to the underlying completion create call."""
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        llm = OllamaLLMClient(settings)
        await llm.chat([{"role": "user", "content": "Hi"}], max_tokens=100)
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] == 100
