"""Shared test fixtures for the RAG pipeline."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from config.settings import Settings


@pytest.fixture
def settings() -> Settings:
    """Return a Settings instance with test defaults."""
    return Settings(
        database_url=SecretStr("sqlite+aiosqlite:///test.db"),
        database_url_sync=SecretStr("sqlite:///test.db"),
        database_url_generated=SecretStr("sqlite+aiosqlite:///test.db"),
        redis_broker_url="redis://localhost:6379/10",
        redis_result_url="redis://localhost:6379/11",
        redis_cache_url="redis://localhost:6379/12",
        minio_endpoint="localhost:9000",
        minio_secure=False,
        milvus_host="localhost",
        milvus_port=19530,
        api_key=SecretStr(""),
    )


@pytest.fixture
async def db_session(settings: Settings):
    """Async DB session backed by aiosqlite for unit tests."""
    from src.metadata.repository import Base

    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def mock_minio_client() -> MagicMock:
    """Mock MinIO client."""
    client = MagicMock()
    client.bucket_exists.return_value = True
    client.put_object.return_value = None
    client.get_object.return_value = MagicMock(read=MagicMock(return_value=b"file content"))
    return client


@pytest.fixture
def mock_drive_service() -> MagicMock:
    """Mock Google Drive service."""
    service = MagicMock()
    return service


@pytest.fixture
def mock_ollama_client() -> AsyncMock:
    """Mock Ollama embedding client (for EmbeddingClient protocol)."""
    client = AsyncMock()
    client.embed.return_value = [[0.1] * 768]
    return client


@pytest.fixture
def mock_httpx_client() -> AsyncMock:
    """Mock httpx.AsyncClient for BatchEmbedder HTTP calls to Ollama."""
    client = AsyncMock()
    client.post.return_value = MagicMock(
        json=MagicMock(return_value={"embeddings": [[0.1] * 768]}),
        status_code=200,
        raise_for_status=MagicMock(),
    )
    return client


@pytest.fixture
def mock_milvus_client() -> MagicMock:
    """Mock Milvus client."""
    client = MagicMock()
    client.search.return_value = []
    return client


@pytest.fixture
def mock_redis_client() -> MagicMock:
    """Mock Redis client for retriever caching tests."""
    client = MagicMock()
    client.get.return_value = None
    client.set.return_value = True
    return client


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Minimal valid-ish PDF bytes for testing (mocked — not a real PDF)."""
    return b"%PDF-1.4 fake pdf content for testing"


@pytest.fixture
def sample_text() -> str:
    """Sample extracted text for chunking/embedding tests."""
    return (
        "# Quarterly Report Q3 2024\n\n"
        "## Revenue\n\n"
        "Total revenue reached $1.2M, a 15% increase over Q2.\n\n"
        "## Expenses\n\n"
        "Operating expenses were $800K.\n\n"
        "## Summary\n\n"
        "Net profit of $400K with healthy margins across all segments."
    )
