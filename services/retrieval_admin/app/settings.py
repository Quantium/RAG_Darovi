from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    api_port: int = 8010
    api_key: SecretStr = SecretStr("")

    database_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@postgres:5432/rag_darovi")
    redis_cache_url: str = "redis://redis:6379/2"

    minio_endpoint: str = "minio:9000"
    minio_access_key: SecretStr = SecretStr("minioadmin")
    minio_secret_key: SecretStr = SecretStr("minioadmin")
    minio_secure: bool = False
    minio_bucket_text: str = "converted-texts"
    minio_bucket_raw: str = "raw-files"
    minio_external_endpoint: str = "http://localhost:9000"
    minio_console_endpoint: str = "http://localhost:9001"

    milvus_host: str = "milvus"
    milvus_port: int = 19530
    milvus_collection: str = "rag_documents"

    embed_api_url: str = "https://api.openai.com/v1"
    embed_api_key: SecretStr = SecretStr("")
    embed_model: str = "text-embedding-3-large"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
