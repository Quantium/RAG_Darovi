from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.app import verify_api_key

response_router = APIRouter(prefix="/responses", tags=["responses"])


@response_router.get("", dependencies=[Depends(verify_api_key)])
async def list_responses(request: Request) -> list[dict]:
    """Return the 500 most recent chat interactions with their ratings and corrections.

    Args:
        request: Incoming FastAPI request carrying app state.

    Returns:
        List of dicts with id, conversation_id, question, answer, rating, correction, and created_at.
    """
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.execute(
            text(
                "SELECT id, conversation_id, question, answer, rating, correction,"
                " created_at AT TIME ZONE 'UTC' AS created_at"
                " FROM chat_interactions"
                " ORDER BY created_at DESC"
                " LIMIT 500"
            )
        )
        rows = result.fetchall()
    return [
        {
            "id": row[0],
            "conversation_id": row[1],
            "question": row[2],
            "answer": row[3],
            "rating": row[4],
            "correction": row[5],
            "created_at": row[6].isoformat() if row[6] else None,
        }
        for row in rows
    ]
