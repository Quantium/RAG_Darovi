from __future__ import annotations

import json
from dataclasses import dataclass, asdict


@dataclass
class ConversationTurn:
    role: str
    content: str


class ConversationStore:
    def __init__(self, redis_client, ttl_seconds: int = 86400) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds

    def get_history(self, conversation_id: str) -> list[ConversationTurn]:
        raw = self._redis.get(self._key(conversation_id))
        if not raw:
            return []
        try:
            payload = json.loads(raw)
            return [ConversationTurn(**item) for item in payload]
        except Exception:
            return []

    def append(self, conversation_id: str, role: str, content: str) -> None:
        history = self.get_history(conversation_id)
        history.append(ConversationTurn(role=role, content=content))
        self._redis.set(self._key(conversation_id), json.dumps([asdict(item) for item in history]), ex=self._ttl)

    @staticmethod
    def _key(conversation_id: str) -> str:
        return f"chatbot:conv:{conversation_id}"
