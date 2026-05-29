from __future__ import annotations

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Ingestion source — local folder only
    local_source_folder: str = ""

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: SecretStr = SecretStr("minioadmin")
    minio_secret_key: SecretStr = SecretStr("minioadmin")
    minio_secure: bool = False
    minio_bucket_raw: str = "raw-files"
    minio_bucket_text: str = "converted-texts"

    # PostgreSQL (async for FastAPI, sync for Celery tasks)
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_darovi"
    )
    database_url_sync: SecretStr = SecretStr(
        "postgresql+psycopg2://postgres:postgres@localhost:5432/rag_darovi"
    )
    database_url_generated: SecretStr = SecretStr(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_darovi"
    )

    # Redis (isolated DBs: broker=0, results=1, cache=2)
    redis_broker_url: str = "redis://localhost:6379/0"
    redis_result_url: str = "redis://localhost:6379/1"
    redis_cache_url: str = "redis://localhost:6379/2"

    # Milvus — use milvus_uri + milvus_token for Zilliz Cloud; host/port for local
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "rag_documents"
    milvus_uri: str = ""
    milvus_token: str = ""

    # OpenAI — embeddings
    embed_api_url: str = "https://api.openai.com/v1"
    embed_api_key: SecretStr = SecretStr("")
    embed_model: str = "text-embedding-3-large"
    embed_dim: int = 3072
    embed_batch_size: int = 64
    embed_request_timeout_s: int = 120

    # LLM (DeepSeek via OpenAI-compat SDK)
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://api.deepseek.com/v1/"
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com/v1/"

    # Scheduler
    embedding_poll_interval_seconds: int = 300
    legacy_ingest_pipeline_enabled: bool = True

    # OCR (Tesseract; fallback when vision circuit breaker is open)
    ocr_language: str = "eng"
    ocr_dpi: int = 300
    ocr_psm: str = ""
    ocr_min_text_chars: int = 40
    ocr_min_alpha_ratio: float = 0.45
    ocr_max_single_char_line_ratio: float = 0.6

    # Vision (OpenAI-compatible: gpt-4o or equivalent)
    vision_enabled: bool = True
    vision_external_base_url: str = "https://api.openai.com/v1"
    vision_external_api_key: str = ""
    vision_external_model: str = "gpt-4o"
    vision_request_timeout_s: int = 180
    vision_max_image_mb: int = 8
    vision_max_pages_per_request: int = 1
    vision_circuit_breaker_threshold: int = 5
    vision_circuit_breaker_reset_s: int = 300
    vision_fallback_to_tesseract: bool = True
    vision_downscale_dpi: int = 200

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_key: SecretStr = SecretStr("")
    api_ssl_certfile: str = ""
    api_ssl_keyfile: str = ""

    @field_validator("ocr_dpi")
    @classmethod
    def _validate_ocr_dpi(cls, value: int) -> int:
        if value < 72 or value > 600:
            raise ValueError("ocr_dpi must be between 72 and 600")
        return value

    @field_validator("ocr_min_text_chars")
    @classmethod
    def _validate_ocr_min_text_chars(cls, value: int) -> int:
        if value < 1:
            raise ValueError("ocr_min_text_chars must be >= 1")
        return value

    @field_validator("ocr_min_alpha_ratio")
    @classmethod
    def _validate_ocr_min_alpha_ratio(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("ocr_min_alpha_ratio must be between 0.0 and 1.0")
        return value

    @field_validator("ocr_max_single_char_line_ratio")
    @classmethod
    def _validate_ocr_max_single_char_line_ratio(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("ocr_max_single_char_line_ratio must be between 0.0 and 1.0")
        return value

    @field_validator("vision_max_image_mb")
    @classmethod
    def _validate_vision_max_image_mb(cls, value: int) -> int:
        if value < 1 or value > 50:
            raise ValueError("vision_max_image_mb must be between 1 and 50")
        return value

    @field_validator("vision_request_timeout_s")
    @classmethod
    def _validate_vision_request_timeout_s(cls, value: int) -> int:
        if value < 5 or value > 1800:
            raise ValueError("vision_request_timeout_s must be between 5 and 1800")
        return value

    @field_validator("vision_circuit_breaker_threshold")
    @classmethod
    def _validate_vision_circuit_breaker_threshold(cls, value: int) -> int:
        if value < 1:
            raise ValueError("vision_circuit_breaker_threshold must be >= 1")
        return value

    @field_validator("vision_downscale_dpi")
    @classmethod
    def _validate_vision_downscale_dpi(cls, value: int) -> int:
        if value < 72 or value > 600:
            raise ValueError("vision_downscale_dpi must be between 72 and 600")
        return value

    # Dashboard — optional HTTP triggers to ingest_raw / extract_text sidecars (Docker DNS)
    ingest_raw_trigger_url: str = ""
    extract_text_trigger_url: str = ""
    extract_text_lock_id: int = 8245101

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
