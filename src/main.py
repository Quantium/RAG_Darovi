from __future__ import annotations

import argparse
import asyncio
import sys

from config.settings import Settings
from src.logging import configure_logging


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="RAG Darovi Pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="Start FastAPI server")
    sub.add_parser("worker", help="Start Celery worker")
    sub.add_parser("beat", help="Start Celery Beat scheduler")
    sub.add_parser("ingest", help="Run one-time full ingestion from Drive")

    query_p = sub.add_parser("query", help="Query documents from CLI")
    query_p.add_argument("text", help="The question to ask")
    query_p.add_argument("--type", dest="doc_type", help="Filter by doc type (doc/sheet/pdf)")

    args = parser.parse_args()
    settings = Settings()

    if args.command == "serve":
        import uvicorn
        uvicorn.run(
            "src.api.app:create_app",
            factory=True,
            host=settings.api_host,
            port=settings.api_port,
        )

    elif args.command == "worker":
        from src.worker.celery_app import app
        app.worker_main(["worker", "--loglevel=info", "-Q", "download,convert,embed,default"])

    elif args.command == "beat":
        from src.worker.celery_app import app
        app.worker_main(["beat", "--loglevel=info"])

    elif args.command == "ingest":
        from src.worker.tasks import run_incremental_sync
        run_incremental_sync.delay()
        print("Ingestion dispatched. Monitor via `GET /status`.")

    elif args.command == "query":
        asyncio.run(_cli_query(settings, args.text, args.doc_type))


async def _cli_query(settings: Settings, query: str, doc_type: str | None) -> None:
    from src.vectorizer.embedder import BatchEmbedder
    from src.vectorizer.milvus_store import MilvusStore
    from src.rag.retriever import Retriever
    from src.rag.llm_client import create_llm_client
    from src.rag.chain import rag_answer

    embedder = BatchEmbedder(settings)
    store = MilvusStore(settings)
    retriever = Retriever(embedder=embedder, vector_store=store)
    llm = create_llm_client(settings)

    answer, sources = await rag_answer(query, retriever, llm, document_type=doc_type)
    print(f"\n{answer}\n")
    if sources:
        print("Sources:")
        for s in sources:
            print(f"  [{s.source_name}] {s.section_title} (score: {s.score:.2f})")


if __name__ == "__main__":
    main()
