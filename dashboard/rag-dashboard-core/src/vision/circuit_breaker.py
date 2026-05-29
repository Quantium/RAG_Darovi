"""Redis-backed circuit breaker for the VLM pipeline.

When the breaker is OPEN, callers should skip the VLM and fall back to
Tesseract (or any cheaper alternative) instead of pounding an unhealthy
upstream. State is persisted in Redis so multiple Celery workers share
the same view.

Failure-open philosophy: if Redis itself is unreachable, the breaker
returns CLOSED so the pipeline keeps moving — the alternative would mean
losing the OCR step every time Redis blips.
"""

from __future__ import annotations

import enum
import time

import structlog

logger = structlog.get_logger()


class CircuitState(str, enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


_STATE_KEY = "vision:cb:state"
_FAILS_KEY = "vision:cb:fails"
_OPENED_AT_KEY = "vision:cb:opened_at"


class CircuitBreaker:
    """Three-state breaker stored in Redis."""

    def __init__(self, redis_client, *, threshold: int, reset_after_s: int) -> None:
        """Initialize the circuit breaker with Redis persistence and thresholds.

        Args:
            redis_client: Connected Redis client for state persistence.
            threshold: Number of consecutive failures before the circuit opens.
            reset_after_s: Seconds to wait in OPEN state before transitioning to HALF_OPEN.
        """
        self._redis = redis_client
        self._threshold = max(1, threshold)
        self._reset_after_s = max(1, reset_after_s)

    def state(self) -> CircuitState:
        """Read and return the current circuit state from Redis.

        Transitions OPEN → HALF_OPEN if the reset window has elapsed.
        Falls back to CLOSED if Redis is unavailable (failure-open philosophy).

        Returns:
            Current CircuitState enum value.
        """
        try:
            raw = self._redis.get(_STATE_KEY)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("vision.cb.redis_unavailable", error=str(exc))
            return CircuitState.CLOSED

        if raw is None:
            return CircuitState.CLOSED

        value = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        if value == CircuitState.OPEN.value:
            opened_at = self._read_opened_at()
            if opened_at and (time.time() - opened_at) >= self._reset_after_s:
                self._safe_set(_STATE_KEY, CircuitState.HALF_OPEN.value)
                return CircuitState.HALF_OPEN
            return CircuitState.OPEN
        if value == CircuitState.HALF_OPEN.value:
            return CircuitState.HALF_OPEN
        return CircuitState.CLOSED

    def allow(self) -> bool:
        """Return True if the circuit is CLOSED or HALF_OPEN (VLM calls permitted).

        Returns:
            False only when the circuit is OPEN.
        """
        return self.state() != CircuitState.OPEN

    def record_failure(self) -> None:
        """Increment the failure counter and open the circuit if the threshold is reached.

        In HALF_OPEN state, any single failure immediately re-opens the circuit.
        No-op if Redis is unavailable.
        """
        try:
            current = self._redis.incr(_FAILS_KEY)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("vision.cb.incr_failed", error=str(exc))
            return

        state = self.state()
        if state == CircuitState.HALF_OPEN:
            self._open()
            return
        if int(current) >= self._threshold:
            self._open()

    def record_success(self) -> None:
        """Reset the failure counter and close the circuit after a successful VLM call."""
        self._safe_delete(_FAILS_KEY)
        self._safe_delete(_OPENED_AT_KEY)
        self._safe_set(_STATE_KEY, CircuitState.CLOSED.value)

    def _open(self) -> None:
        """Transition the circuit to OPEN state and record the timestamp."""
        self._safe_set(_STATE_KEY, CircuitState.OPEN.value)
        self._safe_set(_OPENED_AT_KEY, str(time.time()))
        logger.error("vision.cb.opened", threshold=self._threshold)

    def _read_opened_at(self) -> float | None:
        """Read the timestamp when the circuit was last opened.

        Returns:
            Unix timestamp float, or None if the key is absent or unreadable.
        """
        try:
            raw = self._redis.get(_OPENED_AT_KEY)
        except Exception:  # pragma: no cover - defensive
            return None
        if raw is None:
            return None
        try:
            value = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
            return float(value)
        except (TypeError, ValueError):
            return None

    def _safe_set(self, key: str, value: str, ex: int | None = None) -> None:
        """Set a Redis key, logging a warning if the operation fails.

        Args:
            key: Redis key to set.
            value: String value to store.
            ex: Optional expiry time in seconds.
        """
        try:
            self._redis.set(key, value, ex=ex)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("vision.cb.set_failed", key=key, error=str(exc))

    def _safe_delete(self, key: str) -> None:
        """Delete a Redis key, logging a warning if the operation fails.

        Args:
            key: Redis key to delete.
        """
        try:
            self._redis.delete(key)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("vision.cb.delete_failed", key=key, error=str(exc))
