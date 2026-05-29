from __future__ import annotations

from openai import AsyncOpenAI

from .settings import Settings


class LLMService:
    def __init__(self, settings: Settings) -> None:
        """Initialize the LLM client using settings for the model and base URL.

        Args:
            settings: Application settings providing the LLM API key, model name, and base URL.
        """
        api_key = settings.llm_api_key.get_secret_value() or "dummy"
        self._model = settings.llm_model
        self._client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=api_key)

    async def answer(self, query: str, context: str) -> str:
        """Generate a grounded LLM answer from the provided query and context.

        Args:
            query: The user's question.
            context: Retrieved text to use as the answer's factual basis.

        Returns:
            The model's response text, or an empty string if the content is None.
        """
        messages = [
            {
                "role": "system",
                "content": "Answer strictly from context. If not enough context, say you do not know.",
            },
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
        ]
        response = await self._client.chat.completions.create(model=self._model, messages=messages, temperature=0.1)
        content = response.choices[0].message.content
        return content or ""
