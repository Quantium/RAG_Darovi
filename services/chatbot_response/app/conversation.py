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

    def get_history(self, conversation_id: str, slug: str = "") -> list[ConversationTurn]:
        """Retrieve the full turn history for a conversation from Redis.

        Args:
            conversation_id: Unique identifier of the conversation.
            slug: Licitación slug namespacing the key; empty keeps the legacy flat key.

        Returns:
            Ordered list of ConversationTurn objects, or an empty list if none exist.
        """
        raw = self._redis.get(self._key(conversation_id, slug))
        if not raw:
            return []
        try:
            payload = json.loads(raw)
            return [ConversationTurn(**item) for item in payload]
        except Exception:
            return []

    def append(self, conversation_id: str, role: str, content: str, slug: str = "") -> None:
        """Append a new turn to the conversation history and persist it in Redis.

        Args:
            conversation_id: Unique identifier of the conversation.
            role: Speaker role, either 'user' or 'assistant'.
            content: Text content of the turn.
            slug: Licitación slug namespacing the key; empty keeps the legacy flat key.
        """
        history = self.get_history(conversation_id, slug)
        history.append(ConversationTurn(role=role, content=content))
        self._redis.set(self._key(conversation_id, slug), json.dumps([asdict(item) for item in history]), ex=self._ttl)

    @staticmethod
    def _key(conversation_id: str, slug: str = "") -> str:
        """Build the Redis key for a conversation, namespaced by licitación slug.

        Args:
            conversation_id: Unique identifier of the conversation.
            slug: Licitación slug; empty preserves the pre-multitenancy flat key.

        Returns:
            ``chatbot:conv:<slug>:<id>`` when a slug is given, else ``chatbot:conv:<id>``.
        """
        if slug:
            return f"chatbot:conv:{slug}:{conversation_id}"
        return f"chatbot:conv:{conversation_id}"
