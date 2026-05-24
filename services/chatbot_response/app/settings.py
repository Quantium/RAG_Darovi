from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    api_port: int = 8020
    api_key: SecretStr = SecretStr("")

    retrieval_admin_base_url: str = "http://retrieval-admin-service:8010"

    redis_cache_url: str = "redis://redis:6379/2"
    conversation_ttl_seconds: int = 86400

    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com/v1/"
    llm_api_key: SecretStr = SecretStr("")
    deepseek_api_key: SecretStr = SecretStr("")

    # LLM generation parameters
    llm_temperature: float = 0.1
    llm_top_p: float = 0.95
    llm_frequency_penalty: float = 0.2
    llm_repeat_penalty: float = 1.1
    llm_max_tokens: int = 2048

    # Retrieval context window
    llm_max_context_chars: int = 32000

    # top_k for aggregate vs specific queries
    retrieval_top_k_default: int = 10
    retrieval_top_k_aggregate: int = 40

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
