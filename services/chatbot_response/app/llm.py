from __future__ import annotations

from openai import AsyncOpenAI

from .conversation import ConversationTurn
from .settings import Settings


class LLMService:
    def __init__(self, settings: Settings) -> None:
        api_key = (
            settings.deepseek_api_key.get_secret_value()
            or settings.llm_api_key.get_secret_value()
            or "dummy"
        )
        self._model = settings.llm_model
        self._client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=api_key)
        self._max_context_chars = settings.llm_max_context_chars
        self._temperature = settings.llm_temperature
        self._top_p = settings.llm_top_p
        self._frequency_penalty = settings.llm_frequency_penalty
        self._max_tokens = settings.llm_max_tokens

    _SYSTEM_PROMPT = (
        "Eres un asistente especializado en licitaciones y registros sanitarios de COFEPRIS México. "
        "Responde ÚNICAMENTE con información del contexto proporcionado. NUNCA inventes datos. "
        "El contexto proviene de documentos escaneados con posibles errores de OCR; "
        "interpreta texto parcialmente ilegible con criterio. "
        "Para preguntas de conteo o listado ('¿cuántos?', 'lista todos', etc.): "
        "enumera TODOS los medicamentos/productos/registros que aparezcan en el contexto, "
        "sin omitir ninguno. Si el contexto puede estar incompleto para esa pregunta, adviértelo. "
        "Busca Denominación Distintiva, Denominación Genérica, número de registro sanitario, "
        "titular, fabricante y número de solicitud, aunque estén parcialmente ilegibles. "
        "Si la información no está en el contexto, dilo claramente. "
        "Responde en español y de forma concisa."
    )

    # Keywords that signal aggregate / listing queries needing maximum context
    _AGGREGATE_KEYWORDS = (
        "cuántos", "cuantos", "cuántas", "cuantas", "cuál es el total", "total de",
        "lista", "listado", "enumera", "enumerar", "todos los", "todas las",
        "hay en total", "existen", "medicamentos hay", "productos hay",
        "registros hay", "registros sanitarios hay",
    )

    def _is_aggregate_query(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in self._AGGREGATE_KEYWORDS)

    async def answer(self, *, query: str, context: str, history: list[ConversationTurn]) -> str:
        # Aggregate queries get the full context window; specific queries get half to save tokens
        char_limit = self._max_context_chars if self._is_aggregate_query(query) else self._max_context_chars // 2
        truncated = context[:char_limit]
        messages: list[dict] = [{"role": "system", "content": self._SYSTEM_PROMPT}]
        for turn in history:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": f"Contexto:\n{truncated}\n\nPregunta: {query}"})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=self._temperature,
            top_p=self._top_p,
            frequency_penalty=self._frequency_penalty,
            max_tokens=self._max_tokens,
        )
        return response.choices[0].message.content or ""
