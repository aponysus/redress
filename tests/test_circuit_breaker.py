# tests/test_circuit_breaker.py

from redress.circuit import CircuitBreaker, CircuitState
from redress.errors import ErrorClass


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_circuit_breaker_opens_after_threshold() -> None:
    clock = _FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=2,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.TRANSIENT},
        clock=clock.monotonic,
    )

    assert breaker.state is CircuitState.CLOSED
    assert breaker.allow().allowed
    assert breaker.record_failure(ErrorClass.TRANSIENT) is None
    clock.advance(1.0)
    assert breaker.record_failure(ErrorClass.TRANSIENT) == "circuit_opened"
    assert breaker.state is CircuitState.OPEN

    decision = breaker.allow()
    assert decision.allowed is False
    assert decision.event == "circuit_rejected"


def test_circuit_breaker_half_open_and_close() -> None:
    clock = _FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.TRANSIENT},
        clock=clock.monotonic,
    )

    assert breaker.record_failure(ErrorClass.TRANSIENT) == "circuit_opened"
    clock.advance(5.1)

    decision = breaker.allow()
    assert decision.allowed is True
    assert decision.event == "circuit_half_open"
    assert breaker.record_success() == "circuit_closed"
    assert breaker.state is CircuitState.CLOSED


def test_circuit_breaker_half_open_failure_reopens() -> None:
    clock = _FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.TRANSIENT},
        clock=clock.monotonic,
    )

    assert breaker.record_failure(ErrorClass.TRANSIENT) == "circuit_opened"
    clock.advance(5.1)
    assert breaker.allow().allowed is True
    assert breaker.record_failure(ErrorClass.SERVER_ERROR) == "circuit_opened"
    assert breaker.state is CircuitState.OPEN


def test_circuit_breaker_per_class_threshold() -> None:
    clock = _FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=5,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.TRANSIENT},
        class_thresholds={ErrorClass.RATE_LIMIT: 2},
        clock=clock.monotonic,
    )

    assert breaker.record_failure(ErrorClass.RATE_LIMIT) is None
    assert breaker.record_failure(ErrorClass.RATE_LIMIT) == "circuit_opened"
    assert breaker.state is CircuitState.OPEN


def test_circuit_breaker_rejects_second_half_open_probe() -> None:
    clock = _FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=2.0,
        trip_on={ErrorClass.TRANSIENT},
        clock=clock.monotonic,
    )

    assert breaker.record_failure(ErrorClass.TRANSIENT) == "circuit_opened"
    clock.advance(2.1)
    decision = breaker.allow()
    assert decision.allowed is True
    assert decision.event == "circuit_half_open"

    rejected = breaker.allow()
    assert rejected.allowed is False
    assert rejected.event == "circuit_rejected"

    breaker.record_cancel()
    assert breaker.allow().allowed is True


def test_circuit_breaker_ignores_non_trip_class() -> None:
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.TRANSIENT},
    )

    assert breaker.record_failure(ErrorClass.PERMANENT) is None
    assert breaker.state is CircuitState.CLOSED


def test_circuit_breaker_window_expires() -> None:
    clock = _FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=2,
        window_s=1.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.TRANSIENT},
        clock=clock.monotonic,
    )

    assert breaker.record_failure(ErrorClass.TRANSIENT) is None
    clock.advance(2.0)
    assert breaker.record_failure(ErrorClass.TRANSIENT) is None
    assert breaker.state is CircuitState.CLOSED


def test_circuit_breaker_validation_errors() -> None:
    for kwargs in (
        {"failure_threshold": 0},
        {"window_s": 0.0},
        {"recovery_timeout_s": 0.0},
    ):
        try:
            CircuitBreaker(**kwargs)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError("Expected ValueError.")

    try:
        CircuitBreaker(class_thresholds={ErrorClass.RATE_LIMIT: 0})
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError.")
