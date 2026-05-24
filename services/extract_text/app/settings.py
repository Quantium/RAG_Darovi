from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    minio_endpoint: str = "minio:9000"
    minio_access_key: SecretStr = SecretStr("minioadmin")
    minio_secret_key: SecretStr = SecretStr("minioadmin")
    minio_secure: bool = False
    minio_bucket_raw: str = "raw-files"
    minio_bucket_text: str = "converted-texts"

    database_url_sync: SecretStr = SecretStr(
        "postgresql+psycopg2://postgres:postgres@postgres:5432/rag_darovi"
    )

    extract_text_cron: str = "0 */4 * * *"
    extract_text_batch_size: int = 200
    extract_text_run_on_start: bool = True
    extract_text_lock_id: int = 8245101
    extract_text_http_port: int = 8031
    extract_text_http_enabled: bool = True

    vision_enabled: bool = True
    ocr_min_text_chars: int = 40
    ocr_min_alpha_ratio: float = 0.45
    ocr_max_single_char_line_ratio: float = 0.6

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
