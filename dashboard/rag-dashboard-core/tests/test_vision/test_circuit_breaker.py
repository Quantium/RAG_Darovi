"""Tests for src/vision/circuit_breaker.py — Redis-backed breaker."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from src.vision.circuit_breaker import CircuitBreaker, CircuitState


class FakeRedis:
    """Minimal in-memory Redis substitute supporting the ops used by CircuitBreaker."""

    def __init__(self) -> None:
        """Initialize empty key-value store and TTL registry."""
        self._store: dict[str, str] = {}
        self._ttl: dict[str, float] = {}

    def get(self, key: str) -> bytes | None:
        """Return the value for key as bytes, or None if missing or expired."""
        if key in self._ttl and self._ttl[key] < time.time():
            self._store.pop(key, None)
            self._ttl.pop(key, None)
        val = self._store.get(key)
        return val.encode() if val is not None else None

    def set(self, key: str, value, ex: int | None = None) -> bool:
        """Store a value with an optional TTL in seconds."""
        self._store[key] = str(value)
        if ex is not None:
            self._ttl[key] = time.time() + ex
        return True

    def incr(self, key: str) -> int:
        """Increment the integer value of a key by 1 and return the new value."""
        current = int(self._store.get(key, "0"))
        self._store[key] = str(current + 1)
        return current + 1

    def delete(self, key: str) -> int:
        """Delete a key and return 1."""
        self._store.pop(key, None)
        self._ttl.pop(key, None)
        return 1


class TestCircuitBreaker:
    def test_starts_closed(self):
        """Verify a new circuit breaker starts in CLOSED state and allows calls."""
        cb = CircuitBreaker(FakeRedis(), threshold=3, reset_after_s=60)
        assert cb.state() == CircuitState.CLOSED
        assert cb.allow() is True

    def test_opens_after_threshold_failures(self):
        """Verify the circuit transitions to OPEN after reaching the failure threshold."""
        cb = CircuitBreaker(FakeRedis(), threshold=3, reset_after_s=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state() == CircuitState.OPEN
        assert cb.allow() is False

    def test_record_success_resets_failures(self):
        """Verify record_success closes the circuit and resets the failure counter."""
        cb = CircuitBreaker(FakeRedis(), threshold=3, reset_after_s=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state() == CircuitState.CLOSED
        cb.record_failure()
        cb.record_failure()
        assert cb.state() == CircuitState.CLOSED

    def test_open_state_transitions_to_half_open_after_timeout(self):
        """Verify OPEN transitions to HALF_OPEN once the reset window elapses."""
        redis = FakeRedis()
        cb = CircuitBreaker(redis, threshold=2, reset_after_s=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state() == CircuitState.OPEN

        time.sleep(1.1)
        assert cb.state() == CircuitState.HALF_OPEN
        assert cb.allow() is True

    def test_half_open_failure_returns_to_open(self):
        """Verify a failure in HALF_OPEN state immediately re-opens the circuit."""
        redis = FakeRedis()
        cb = CircuitBreaker(redis, threshold=2, reset_after_s=1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(1.1)

        assert cb.state() == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state() == CircuitState.OPEN

    def test_half_open_success_closes_breaker(self):
        """Verify a success in HALF_OPEN state closes the circuit and resets the counter."""
        redis = FakeRedis()
        cb = CircuitBreaker(redis, threshold=2, reset_after_s=1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(1.1)

        assert cb.state() == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state() == CircuitState.CLOSED

    def test_redis_failure_is_non_fatal(self):
        """Verify the breaker is non-fatal and allows calls when Redis itself is unavailable."""
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
