import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from .errors import ErrorClass
from .events import EventName


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _BreakerAdmission:
    generation: int
    completed: bool = False


@dataclass(frozen=True)
class _BreakerDecision:
    allowed: bool
    state: CircuitState
    event: str | None = None
    _admission: _BreakerAdmission | None = field(default=None, repr=False, compare=False)


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
        self._generation = 0
        self._probe: _BreakerAdmission | None = None
        self._failures: deque[float] = deque()
        self._class_failures: dict[ErrorClass, deque[float]] = {}
        # Owned completion checks and the public record_* methods share this lock.
        self._lock = threading.RLock()

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
                    self._probe = _BreakerAdmission(self._generation)
                    return _BreakerDecision(
                        True, self._state, EventName.CIRCUIT_HALF_OPEN.value, self._probe
                    )
                return _BreakerDecision(False, self._state, EventName.CIRCUIT_REJECTED.value)

            if self._state is CircuitState.HALF_OPEN:
                if self._probe is not None:
                    return _BreakerDecision(
                        False,
                        self._state,
                        EventName.CIRCUIT_REJECTED.value,
                    )
                self._probe = _BreakerAdmission(self._generation)
                return _BreakerDecision(True, self._state, None, self._probe)

            return _BreakerDecision(True, self._state, None, _BreakerAdmission(self._generation))

    def record_success(self) -> str | None:
        with self._lock:
            return self._record_success_locked()

    def record_failure(self, klass: ErrorClass) -> str | None:
        now = self._clock()
        with self._lock:
            return self._record_failure_locked(klass, now)

    def record_cancel(self) -> None:
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._probe = None

    def _complete(
        self,
        decision: _BreakerDecision,
        outcome: Literal["success", "failure", "cancel"],
        klass: ErrorClass | None = None,
    ) -> str | None:
        """Settle a policy admission once, ignoring completions from older generations."""
        with self._lock:
            admission = decision._admission
            if admission is None or admission.completed:
                return None
            if admission.generation != self._generation:
                admission.completed = True
                return None
            if self._state is CircuitState.HALF_OPEN and self._probe is not admission:
                admission.completed = True
                return None
            if outcome == "success":
                event = self.record_success()
            elif outcome == "failure":
                assert klass is not None
                event = self.record_failure(klass)
            else:
                self.record_cancel()
                event = None
            admission.completed = True
            return event

    def _record_success_locked(self) -> str | None:
        if self._state is CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._generation += 1
            self._opened_at = None
            self._probe = None
            self._clear_failures()
            return EventName.CIRCUIT_CLOSED.value
        return None

    def _record_failure_locked(self, klass: ErrorClass, now: float) -> str | None:
        if self._state is CircuitState.HALF_OPEN:
            should_open = True
        elif self._state is CircuitState.OPEN or klass not in self._trip_on:
            return None
        else:
            should_open = self._note_failure(klass, now)
        if should_open:
            self._state = CircuitState.OPEN
            self._generation += 1
            self._opened_at = now
            self._probe = None
            self._clear_failures()
            return EventName.CIRCUIT_OPENED.value
        return None

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
