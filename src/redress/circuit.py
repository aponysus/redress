import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from .errors import ErrorClass


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class _BreakerDecision:
    allowed: bool
    state: CircuitState
    event: str | None = None


class CircuitBreaker:
    """
    Simple circuit breaker with open/half-open/closed states.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        window_s: float = 60.0,
        recovery_timeout_s: float = 30.0,
        trip_on: set[ErrorClass] | None = None,
        class_thresholds: Mapping[ErrorClass, int] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1.")
        if window_s <= 0:
            raise ValueError("window_s must be > 0.")
        if recovery_timeout_s <= 0:
            raise ValueError("recovery_timeout_s must be > 0.")

        class_thresholds = dict(class_thresholds or {})
        for klass, threshold in class_thresholds.items():
            if threshold < 1:
                raise ValueError(
                    f"class_thresholds for {getattr(klass, 'name', klass)!r} must be >= 1."
                )

        if trip_on is None:
            trip_on = {ErrorClass.TRANSIENT, ErrorClass.SERVER_ERROR}
        else:
            trip_on = set(trip_on)
        trip_on.update(class_thresholds.keys())

        self._failure_threshold = failure_threshold
        self._window_s = window_s
        self._recovery_timeout_s = recovery_timeout_s
        self._trip_on = trip_on
        self._class_thresholds = class_thresholds
        self._clock = clock

        self._state = CircuitState.CLOSED
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._failures: deque[float] = deque()
        self._class_failures: dict[ErrorClass, deque[float]] = {}
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def allow(self) -> _BreakerDecision:
        now = self._clock()
        with self._lock:
            if self._state is CircuitState.OPEN:
                opened_at = self._opened_at
                if opened_at is None:
                    opened_at = now
                    self._opened_at = now
                if now - opened_at >= self._recovery_timeout_s:
                    self._state = CircuitState.HALF_OPEN
                    self._probe_in_flight = True
                    return _BreakerDecision(True, self._state, "circuit_half_open")
                return _BreakerDecision(False, self._state, "circuit_rejected")

            if self._state is CircuitState.HALF_OPEN:
                if self._probe_in_flight:
                    return _BreakerDecision(False, self._state, "circuit_rejected")
                self._probe_in_flight = True
                return _BreakerDecision(True, self._state, None)

            return _BreakerDecision(True, self._state, None)

    def record_success(self) -> str | None:
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._opened_at = None
                self._probe_in_flight = False
                self._clear_failures()
                return "circuit_closed"
            return None

    def record_failure(self, klass: ErrorClass) -> str | None:
        now = self._clock()
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = now
                self._probe_in_flight = False
                self._clear_failures()
                return "circuit_opened"

            if self._state is CircuitState.OPEN:
                return None

            if klass not in self._trip_on:
                return None

            should_open = self._note_failure(klass, now)
            if should_open:
                self._state = CircuitState.OPEN
                self._opened_at = now
                self._clear_failures()
                return "circuit_opened"
            return None

    def record_cancel(self) -> None:
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._probe_in_flight = False

    def _note_failure(self, klass: ErrorClass, now: float) -> bool:
        self._prune(self._failures, now)
        self._failures.append(now)

        threshold = self._class_thresholds.get(klass)
        if threshold is not None:
            bucket = self._class_failures.get(klass)
            if bucket is None:
                bucket = deque()
                self._class_failures[klass] = bucket
            self._prune(bucket, now)
            bucket.append(now)
            if len(bucket) >= threshold:
                return True

        return len(self._failures) >= self._failure_threshold

    def _prune(self, bucket: deque[float], now: float) -> None:
        cutoff = now - self._window_s
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def _clear_failures(self) -> None:
        self._failures.clear()
        self._class_failures.clear()
