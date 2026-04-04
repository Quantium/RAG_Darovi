from __future__ import annotations

from typing import AsyncIterator

import structlog

from src.rag.conversation import ConversationStore, ConversationTurn
from src.rag.llm_client import LLMClient
from src.rag.retriever import RetrievedChunk, Retriever

logger = structlog.get_logger()

SYSTEM_PROMPT = (
    "Answer the user's question based on the provided context. "
    "Cite sources using [Source: filename | Section: section] format. "
    "If the context doesn't contain relevant information, say so."
)


def _build_messages(
    query: str,
    chunks: list[RetrievedChunk],
    history: list[ConversationTurn] | None = None,
) -> list[dict[str, str]]:
    context = "\n\n".join(
        f"[Source: {c.source_name} | Section: {c.section_title}]\n{c.text}"
        for c in chunks
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    if history:
        for turn in history:
            messages.append({"role": turn.role, "content": turn.content})
    
    messages.append(
        {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"}
    )
    return messages


async def rag_answer(
    query: str,
    retriever: Retriever,
    llm: LLMClient,
    top_k: int = 10,
    document_type: str | None = None,
    conversation_store: ConversationStore | None = None,
    conversation_id: str | None = None,
) -> tuple[str, list[RetrievedChunk]]:
    """Retrieve relevant chunks and generate a complete answer."""
    chunks = await retriever.retrieve(query, top_k=top_k, document_type=document_type)
    
    history = None
    if conversation_store and conversation_id:
        history = conversation_store.get_history(conversation_id)
        
    messages = _build_messages(query, chunks, history)
    answer = await llm.chat(messages)

    if conversation_store and conversation_id:
        conversation_store.append(conversation_id, "user", query)
        conversation_store.append(conversation_id, "assistant", answer)

    logger.info("rag.answer", query_length=len(query), chunks=len(chunks))
    return answer, chunks


async def rag_answer_stream(
    query: str,
    retriever: Retriever,
    llm: LLMClient,
    top_k: int = 10,
    document_type: str | None = None,
    conversation_store: ConversationStore | None = None,
    conversation_id: str | None = None,
) -> tuple[AsyncIterator[str], list[RetrievedChunk]]:
    """Retrieve relevant chunks and stream the answer token by token.

    Returns (token_iterator, chunks). Chunks are available immediately;
    iterate the token_iterator to get the streamed answer.
    """
    chunks = await retriever.retrieve(query, top_k=top_k, document_type=document_type)
    
    history = None
    if conversation_store and conversation_id:
        history = conversation_store.get_history(conversation_id)
        
    messages = _build_messages(query, chunks, history)
    token_stream = llm.chat_stream(messages)
    
    logger.info("rag.answer_stream_started", query_length=len(query), chunks=len(chunks))
    return token_stream, chunks
