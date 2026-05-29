from __future__ import annotations

import asyncio
from functools import partial
from uuid import uuid4

import bcrypt
import psycopg2
import redis
from fastapi import HTTPException, Request

SESSION_PREFIX = "chatbot:session:"


# ── Session helpers (Redis) ────────────────────────────────────────────────────

def create_session(redis_client: redis.Redis, username: str) -> str:
    """Create a new session token for a user and persist it in Redis.

    Args:
        redis_client: Connected Redis client.
        username: Authenticated username to associate with the token.

    Returns:
        Newly generated UUID session token.
    """
    token = str(uuid4())
    redis_client.set(f"{SESSION_PREFIX}{token}", username)
    # No TTL — session never expires until explicit logout
    return token


def delete_session(redis_client: redis.Redis, token: str) -> None:
    """Remove a session token from Redis, effectively logging out the user.

    Args:
        redis_client: Connected Redis client.
        token: Session token to revoke.
    """
    redis_client.delete(f"{SESSION_PREFIX}{token}")


def get_session_username(redis_client: redis.Redis, token: str) -> str | None:
    """Look up the username associated with a session token in Redis.

    Args:
        redis_client: Connected Redis client.
        token: Session token to look up.

    Returns:
        Username string if the token exists, or None if it is missing or expired.
    """
    raw = redis_client.get(f"{SESSION_PREFIX}{token}")
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, bytes) else raw


def check_ws_session(redis_client: redis.Redis, token: str | None) -> bool:
    """Return True if the given token maps to a valid session in Redis.

    Args:
        redis_client: Connected Redis client.
        token: Session token from the WebSocket query string, or None if absent.

    Returns:
        True when the session is valid, False when the token is missing or unknown.
    """
    if not token:
        return False
    return get_session_username(redis_client, token) is not None


# ── User verification (Postgres, sync) ────────────────────────────────────────

def _verify_user_sync(db_url: str, username: str, password: str) -> bool:
    """Synchronously verify user credentials against the chat_users table.

    Args:
        db_url: SQLAlchemy-style database URL (driver prefix is stripped internally).
        username: Username to look up.
        password: Plain-text password to check against the stored bcrypt hash.

    Returns:
        True if the username exists and the password matches, False otherwise.
    """
    # Strip driver prefix — psycopg2.connect does not accept SQLAlchemy-style URLs
    connect_url = db_url.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(connect_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT password_hash FROM chat_users WHERE username = %s",
                (username,),
            )
            row = cur.fetchone()
        if row is None:
            return False
        return bcrypt.checkpw(password.encode("utf-8"), row[0].encode("utf-8"))
    finally:
        conn.close()


async def verify_user(db_url: str, username: str, password: str) -> bool:
    """Asynchronously verify user credentials by offloading the blocking DB call.

    Args:
        db_url: SQLAlchemy-style database URL.
        username: Username to verify.
        password: Plain-text password to check.

    Returns:
        True if credentials are valid, False otherwise.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_verify_user_sync, db_url, username, password))


# ── FastAPI dependency: require valid session token ────────────────────────────

async def require_session(request: Request) -> str:
    """FastAPI dependency that enforces a valid session token on protected routes.

    Accepts the token via 'Authorization: Bearer <token>' header or 'token' query param.

    Args:
        request: Incoming FastAPI request with app state and headers.

    Returns:
        The authenticated username associated with the session.

    Raises:
        HTTPException: 401 if no token is provided or the token is invalid/expired.
    """
    redis_client: redis.Redis = request.app.state.redis_client
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        token: str | None = authorization[7:]
    else:
        token = request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = get_session_username(redis_client, token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return username
