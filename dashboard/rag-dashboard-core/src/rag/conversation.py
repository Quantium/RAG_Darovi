from __future__ import annotations

import json
from dataclasses import dataclass

import redis
import structlog

logger = structlog.get_logger()

MAX_HISTORY_TURNS = 10
CONVERSATION_TTL = 3600  # 1 hour


def count_active_chat_sessions(redis_client: redis.Redis) -> tuple[int, int]:
    """Count non-expired conversation keys: (legacy conv:*, chatbot chatbot:conv:*)."""
    legacy = sum(1 for _ in redis_client.scan_iter(match="conv:*", count=500))
    chatbot = sum(1 for _ in redis_client.scan_iter(match="chatbot:conv:*", count=500))
    return legacy, chatbot


@dataclass
class ConversationTurn:
    role: str  # "user" or "assistant"
    content: str


class ConversationStore:
    def __init__(self, redis_url: str) -> None:
        """Initialize the store with a Redis URL.

        Args:
            redis_url: Redis connection URL (e.g. 'redis://redis:6379/2').
        """
        self._redis = redis.Redis.from_url(redis_url)

    def get_history(self, conversation_id: str) -> list[ConversationTurn]:
        """Retrieve the conversation turn history from Redis.

        Args:
            conversation_id: Unique identifier of the conversation.

        Returns:
            Ordered list of ConversationTurn objects, or an empty list on error or cache miss.
        """
        try:
            raw = self._redis.get(f"conv:{conversation_id}")
            if not raw:
                return []
            payload = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            turns = json.loads(payload)
            return [ConversationTurn(**t) for t in turns]
        except Exception as exc:
            logger.warning("conversation.get_error", conversation_id=conversation_id, error=str(exc))
            return []

    def append(self, conversation_id: str, role: str, content: str) -> None:
        """Append a new turn to the conversation and persist it in Redis with a TTL.

        Trims the history to at most MAX_HISTORY_TURNS * 2 entries to bound context size.

        Args:
            conversation_id: Unique identifier of the conversation.
            role: Speaker role, either 'user' or 'assistant'.
            content: Text content of the turn.
        """
        try:
            history = self.get_history(conversation_id)
            history.append(ConversationTurn(role=role, content=content))
            # Keep only the last N turns to bound context size
            # history turns are user + assistant, so * 2
            history = history[-(MAX_HISTORY_TURNS * 2) :]
            self._redis.set(
                f"conv:{conversation_id}",
                json.dumps([{"role": t.role, "content": t.content} for t in history]),
                ex=CONVERSATION_TTL,
            )
        except Exception as exc:
            logger.warning("conversation.append_error", conversation_id=conversation_id, error=str(exc))

    def clear(self, conversation_id: str) -> None:
        """Delete the conversation history key from Redis.

        Args:
            conversation_id: Unique identifier of the conversation to clear.
        """
        try:
            self._redis.delete(f"conv:{conversation_id}")
        except Exception as exc:
            logger.warning("conversation.clear_error", conversation_id=conversation_id, error=str(exc))
