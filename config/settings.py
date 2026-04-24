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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
