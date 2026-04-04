from __future__ import annotations

from contextlib import asynccontextmanager

import redis
import structlog
from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import create_async_engine

from config.settings import Settings
from src.logging import configure_logging
from src.metadata.repository import init_db
from src.rag.llm_client import create_llm_client
from src.rag.retriever import Retriever
from src.rag.conversation import ConversationStore
from src.vectorizer.embedder import BatchEmbedder
from src.vectorizer.milvus_store import MilvusStore
from src.worker.task_helpers import ensure_milvus_collection

logger = structlog.get_logger()

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


from starlette.requests import HTTPConnection

async def verify_api_key(request: HTTPConnection) -> None:
    """Middleware dependency: skip auth if API_KEY is not configured (dev mode)."""
    settings: Settings = request.app.state.settings
    configured_key = settings.api_key.get_secret_value()
    if not configured_key:
        return  # No key configured — auth disabled (dev mode)
    
    api_key = request.headers.get("X-API-Key")
    if api_key != configured_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = Settings()
    logger.info("app.startup", provider=settings.llm_provider)

    # Database
    await init_db(settings.database_url.get_secret_value())
    engine = create_async_engine(settings.database_url.get_secret_value())

    # Milvus
    ensure_milvus_collection(settings)

    # Redis cache (DB 12 — as per settings)
    cache_client = redis.Redis.from_url(settings.redis_cache_url)

    # Conversation store
    conversation_store = ConversationStore(settings.redis_cache_url)

    # Services
    embedder = BatchEmbedder(settings)
    vector_store = MilvusStore(settings)
    retriever = Retriever(embedder=embedder, vector_store=vector_store, cache=cache_client)
    llm = create_llm_client(settings)

    app.state.settings = settings
    app.state.engine = engine
    app.state.retriever = retriever
    app.state.llm = llm
    app.state.embedder = embedder
    app.state.vector_store = vector_store
    app.state.conversation_store = conversation_store

    yield

    # Shutdown
    cache_client.close()
    await engine.dispose()
    logger.info("app.shutdown")


def create_app() -> FastAPI:
    from src.api.routes import router

    app = FastAPI(
        title="RAG Darovi",
        version="1.0.0",
        lifespan=lifespan,
    )
    # Note: Dependencies are applied to the router or specific routes to allow 
    # the verify_api_key to access app.state.settings which is only populated after lifespan starts.
    # But FastAPI doesn't allow Depends(verify_api_key) in create_app() to access state easily 
    # before it's set. We'll handle auth in the router.
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    
    # Static files mounted AFTER router — routes take priority, static is fallback
    import os
    if os.path.exists("static"):
        app.mount("/", StaticFiles(directory="static", html=True), name="static")
    
    return app
