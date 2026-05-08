from __future__ import annotations

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Ingestion source
    ingest_source: str = "drive"  # supported: drive | local
    local_source_folder: str = ""

    # Google Drive (read-only)
    google_application_credentials: str = "credentials/service-account.json"
    drive_folder_id: str = ""

    # Google Drive OAuth (single-tenant UI flow). If client_id is empty, only service-account mode is used.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: SecretStr = SecretStr("")
    google_oauth_redirect_uri: str = "http://127.0.0.1:8000/auth/google/callback"
    # Fernet key (urlsafe base64, 32 bytes) for encrypting refresh tokens at rest. Empty = store plaintext (dev only).
    token_encryption_key: SecretStr = SecretStr("")
    # Secret for Starlette session cookies (OAuth state + browser session for /drive/*).
    app_session_secret: SecretStr = SecretStr("change-me-in-production")

    # Google Sheets (write — may share the same SA file)
    google_sheets_credentials: str = "credentials/service-account.json"

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
    # Async URL for LLM-generated SQL output (restricted `generated` schema in production)
    database_url_generated: SecretStr = SecretStr(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_darovi"
    )

    # Redis (isolated DBs: broker=0, results=1, cache=2)
    redis_broker_url: str = "redis://localhost:6379/0"
    redis_result_url: str = "redis://localhost:6379/1"
    redis_cache_url: str = "redis://localhost:6379/2"

    # Milvus
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "rag_documents"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    embed_model: str = "nomic-embed-text"
    embed_dim: int = 768
    embed_batch_size: int = 64
    # Docker entrypoint / ops: comma-separated models to pull (optional; not read by app logic).
    ollama_pull_models: str = ""

    # LLM
    llm_provider: str = "ollama"
    llm_model: str = "llama3"
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "http://localhost:11434/v1/"
    # DeepSeek (optional explicit overrides when llm_provider=deepseek)
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com/v1/"

    # Scheduler
    sync_interval_hours: int = 24

    # OCR (legacy Tesseract; kept as fallback when vision is unavailable)
    ocr_language: str = "eng"
    ocr_dpi: int = 300
    ocr_psm: str = ""
    ocr_min_text_chars: int = 40
    ocr_min_alpha_ratio: float = 0.45
    ocr_max_single_char_line_ratio: float = 0.6

    # Vision-Language Model (Llama-3.2-Vision via Ollama)
    # Replaces Tesseract OCR with a structured text + key-value extractor.
    vision_enabled: bool = True
    vision_base_url: str = "http://localhost:11436"
    vision_model: str = "llama3.2-vision:11b"
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
    # TLS for uvicorn (paths to PEM files). Both empty = HTTP only.
    # In Docker, e.g. /etc/rag/certs/cert.pem and /etc/rag/certs/key.pem
    api_ssl_certfile: str = ""
    api_ssl_keyfile: str = ""

    @field_validator("ingest_source")
    @classmethod
    def _validate_ingest_source(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"drive", "local"}:
            raise ValueError("ingest_source must be one of: drive, local")
        return normalized

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
