from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    local_source_folder: str = ""

    minio_endpoint: str = "minio:9000"
    minio_access_key: SecretStr = SecretStr("minioadmin")
    minio_secret_key: SecretStr = SecretStr("minioadmin")
    minio_secure: bool = False
    minio_bucket_raw: str = "raw-files"

    database_url_sync: SecretStr = SecretStr(
        "postgresql+psycopg2://postgres:postgres@postgres:5432/rag_darovi"
    )

    ingest_raw_cron: str = "0 * * * *"
    ingest_raw_page_size: int = 200
    ingest_raw_run_on_start: bool = True
    ingest_raw_http_port: int = 8030
    ingest_raw_http_enabled: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
