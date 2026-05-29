from __future__ import annotations

import json
from dataclasses import dataclass, asdict


@dataclass
class ConversationTurn:
    role: str
    content: str


class ConversationStore:
    def __init__(self, redis_client, ttl_seconds: int = 86400) -> None:
        """Initialize the store with a Redis client and conversation TTL.

        Args:
            redis_client: Connected Redis client used for persistence.
            ttl_seconds: Time-to-live in seconds for each conversation key.
        """
        self._redis = redis_client
        self._ttl = ttl_seconds

    def get_history(self, conversation_id: str) -> list[ConversationTurn]:
        """Retrieve the full turn history for a conversation from Redis.

        Args:
            conversation_id: Unique identifier of the conversation.

        Returns:
            Ordered list of ConversationTurn objects, or an empty list if none exist.
        """
        raw = self._redis.get(self._key(conversation_id))
        if not raw:
            return []
        try:
            payload = json.loads(raw)
            return [ConversationTurn(**item) for item in payload]
        except Exception:
            return []

    def append(self, conversation_id: str, role: str, content: str) -> None:
        """Append a new turn to the conversation history and persist it in Redis.

        Args:
            conversation_id: Unique identifier of the conversation.
            role: Speaker role, either 'user' or 'assistant'.
            content: Text content of the turn.
        """
        history = self.get_history(conversation_id)
        history.append(ConversationTurn(role=role, content=content))
        self._redis.set(self._key(conversation_id), json.dumps([asdict(item) for item in history]), ex=self._ttl)

    @staticmethod
    def _key(conversation_id: str) -> str:
        """Build the Redis key for a given conversation ID.

        Args:
            conversation_id: Unique identifier of the conversation.

        Returns:
            Namespaced Redis key string.
        """
        return f"chatbot:conv:{conversation_id}"
