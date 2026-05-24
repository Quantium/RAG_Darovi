"""Tests for src/vision/circuit_breaker.py — Redis-backed breaker."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from src.vision.circuit_breaker import CircuitBreaker, CircuitState


class FakeRedis:
    """Minimal in-memory redis substitute supporting the ops we use."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttl: dict[str, float] = {}

    def get(self, key: str) -> bytes | None:
        if key in self._ttl and self._ttl[key] < time.time():
            self._store.pop(key, None)
            self._ttl.pop(key, None)
        val = self._store.get(key)
        return val.encode() if val is not None else None

    def set(self, key: str, value, ex: int | None = None) -> bool:
        self._store[key] = str(value)
        if ex is not None:
            self._ttl[key] = time.time() + ex
        return True

    def incr(self, key: str) -> int:
        current = int(self._store.get(key, "0"))
        self._store[key] = str(current + 1)
        return current + 1

    def delete(self, key: str) -> int:
        self._store.pop(key, None)
        self._ttl.pop(key, None)
        return 1


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker(FakeRedis(), threshold=3, reset_after_s=60)
        assert cb.state() == CircuitState.CLOSED
        assert cb.allow() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(FakeRedis(), threshold=3, reset_after_s=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state() == CircuitState.OPEN
        assert cb.allow() is False

    def test_record_success_resets_failures(self):
        cb = CircuitBreaker(FakeRedis(), threshold=3, reset_after_s=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state() == CircuitState.CLOSED
        cb.record_failure()
        cb.record_failure()
        assert cb.state() == CircuitState.CLOSED

    def test_open_state_transitions_to_half_open_after_timeout(self):
        redis = FakeRedis()
        cb = CircuitBreaker(redis, threshold=2, reset_after_s=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state() == CircuitState.OPEN

        time.sleep(1.1)
        assert cb.state() == CircuitState.HALF_OPEN
        assert cb.allow() is True

    def test_half_open_failure_returns_to_open(self):
        redis = FakeRedis()
        cb = CircuitBreaker(redis, threshold=2, reset_after_s=1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(1.1)

        assert cb.state() == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state() == CircuitState.OPEN

    def test_half_open_success_closes_breaker(self):
        redis = FakeRedis()
        cb = CircuitBreaker(redis, threshold=2, reset_after_s=1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(1.1)

        assert cb.state() == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state() == CircuitState.CLOSED

    def test_redis_failure_is_non_fatal(self):
        broken = MagicMock()
        broken.get.side_effect = ConnectionError("redis down")
        broken.set.side_effect = ConnectionError("redis down")
        broken.incr.side_effect = ConnectionError("redis down")
        broken.delete.side_effect = ConnectionError("redis down")

        cb = CircuitBreaker(broken, threshold=2, reset_after_s=1)
        # Should NOT raise when redis is unavailable; failing-open keeps pipeline running.
        assert cb.allow() is True
        cb.record_failure()
        cb.record_success()
