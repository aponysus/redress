# tests/test_async_policy.py


import asyncio
import importlib
from typing import Any

import pytest

from redress import SleepDecision
from redress.circuit import CircuitBreaker, CircuitState
from redress.classify import Classification, default_classifier
from redress.errors import (
    AbortRetryError,
    CircuitOpenError,
    ErrorClass,
    PermanentError,
    RateLimitError,
    RetryExhaustedError,
    StopReason,
)
from redress.events import EventName
from redress.policy import AsyncPolicy, AsyncRetry, AsyncRetryPolicy, AttemptDecision, MetricHook
from redress.strategies import BackoffContext

_retry_mod = importlib.import_module("redress.policy.retry_helpers")
_state_mod = importlib.import_module("redress.policy.state")


def _collect_metrics() -> tuple[MetricHook, list[tuple[str, int, float, dict[str, Any]]]]:
    events: list[tuple[str, int, float, dict[str, Any]]] = []

    def hook(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        events.append((event, attempt, sleep_s, tags))

    return hook, events


def _no_sleep_strategy(_: int, __: ErrorClass, ___: float | None) -> float:
    return 0.0


class _FakeTime:
    def __init__(self, start: float | None = None) -> None:
        self._now = start or 0.0

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_async_policy_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"n": 0}

    async def func() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RateLimitError("429")
        return "ok"

    metric_hook, events = _collect_metrics()

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        strategy=_no_sleep_strategy,
        deadline_s=5.0,
        max_attempts=5,
    )

    result = asyncio.run(policy.call(func, on_metric=metric_hook, operation="async_test"))
    assert result == "ok"
    assert attempts["n"] == 3

    retry_events = [event for event in events if event[0] == "retry"]
    assert len(retry_events) == 2
    success_events = [event for event in events if event[0] == "success"]
    assert len(success_events) == 1
    assert success_events[0][3]["operation"] == "async_test"


def test_async_attempt_hooks_retry_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []
    attempts = {"n": 0}

    def on_start(ctx: Any) -> None:
        calls.append(("start", ctx))

    def on_end(ctx: Any) -> None:
        calls.append(("end", ctx))

    async def func() -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("boom")
        return "ok"

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    policy = AsyncRetryPolicy(
        classifier=lambda exc: ErrorClass.TRANSIENT,
        strategy=_no_sleep_strategy,
        max_attempts=3,
    )

    result = asyncio.run(policy.call(func, on_attempt_start=on_start, on_attempt_end=on_end))
    assert result == "ok"
    assert [entry[0] for entry in calls] == ["start", "end", "start", "end"]

    end1 = calls[1][1]
    end2 = calls[3][1]
    assert end1.decision is AttemptDecision.RETRY
    assert end1.classification is not None
    assert end1.classification.klass is ErrorClass.TRANSIENT
    assert end2.decision is AttemptDecision.SUCCESS
    assert end2.result == "ok"


def test_async_policy_permanent_error_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def func() -> None:
        calls["n"] += 1
        raise PermanentError("stop")

    metric_hook, events = _collect_metrics()

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        strategy=_no_sleep_strategy,
        deadline_s=5.0,
        max_attempts=3,
    )

    with pytest.raises(PermanentError):
        asyncio.run(policy.call(func, on_metric=metric_hook))

    assert calls["n"] == 1
    assert len(events) == 1
    event, attempt, sleep_s, tags = events[0]
    assert event == EventName.PERMANENT_FAIL.value
    assert attempt == 1
    assert sleep_s == 0.0
    assert tags["class"] == ErrorClass.PERMANENT.name


def test_async_policy_abort_if_stops_before_attempt() -> None:
    calls = {"func": 0, "classifier": 0}

    async def func() -> None:
        calls["func"] += 1
        raise RuntimeError("boom")

    def classifier(_: BaseException) -> ErrorClass:
        calls["classifier"] += 1
        return ErrorClass.TRANSIENT

    policy = AsyncRetryPolicy(
        classifier=classifier,
        strategy=_no_sleep_strategy,
        deadline_s=5.0,
        max_attempts=3,
    )

    with pytest.raises(AbortRetryError):
        asyncio.run(policy.call(func, abort_if=lambda: True))

    assert calls["func"] == 0
    assert calls["classifier"] == 0


def test_async_policy_abort_if_skips_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"func": 0}

    async def func() -> None:
        calls["func"] += 1
        raise RateLimitError("429")

    checks = iter([False, False, True])

    def abort_if() -> bool:
        return next(checks)

    slept = {"called": False}

    async def fake_sleep(_: float) -> None:
        slept["called"] = True

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", fake_sleep)

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        strategy=lambda ctx: 1.0,
        deadline_s=5.0,
        max_attempts=3,
    )

    with pytest.raises(AbortRetryError):
        asyncio.run(policy.call(func, abort_if=abort_if))

    assert calls["func"] == 1
    assert slept["called"] is False


def test_async_policy_execute_success_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def func() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError("429")
        return "ok"

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        strategy=_no_sleep_strategy,
        deadline_s=5.0,
        max_attempts=5,
    )

    outcome = asyncio.run(policy.execute(func))
    assert outcome.ok is True
    assert outcome.value == "ok"
    assert outcome.attempts == 3
    assert outcome.stop_reason is None


def test_async_policy_execute_result_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def func() -> str:
        return "bad"

    def result_classifier(_: str) -> ErrorClass:
        return ErrorClass.TRANSIENT

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        result_classifier=result_classifier,
        strategy=_no_sleep_strategy,
        deadline_s=5.0,
        max_attempts=1,
    )

    outcome = asyncio.run(policy.execute(func))
    assert outcome.ok is False
    assert outcome.stop_reason == StopReason.MAX_ATTEMPTS_GLOBAL
    assert outcome.attempts == 1
    assert outcome.cause == "result"
    assert outcome.last_result == "bad"


def test_async_policy_sleep_handler_defers_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    async def func() -> None:
        raise RuntimeError("boom")

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    sleep_calls: list[float] = []
    contexts: list[BackoffContext] = []

    def sleep_fn(ctx: BackoffContext, sleep_s: float) -> SleepDecision:
        contexts.append(ctx)
        sleep_calls.append(sleep_s)
        return SleepDecision.DEFER

    async def fail_sleep(_: float) -> None:
        raise AssertionError("sleep should not be called for DEFER")

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", fail_sleep)
    metric_hook, events = _collect_metrics()

    policy = AsyncRetryPolicy(
        classifier=classifier,
        strategy=lambda ctx: 1.0,
        deadline_s=5.0,
        max_attempts=3,
    )

    outcome = asyncio.run(policy.execute(func, on_metric=metric_hook, sleep=sleep_fn))
    assert outcome.ok is False
    assert outcome.stop_reason == StopReason.SCHEDULED
    assert outcome.next_sleep_s == 1.0
    assert sleep_calls == [1.0]
    assert contexts[0].classification.klass is ErrorClass.TRANSIENT

    scheduled = next(event for event in events if event[0] == EventName.SCHEDULED.value)
    assert scheduled[3]["stop_reason"] == StopReason.SCHEDULED.value


def test_async_policy_sleep_handler_aborts_call(monkeypatch: pytest.MonkeyPatch) -> None:
    async def func() -> None:
        raise RuntimeError("boom")

    def sleep_fn(_: BackoffContext, __: float) -> SleepDecision:
        return SleepDecision.ABORT

    async def fail_sleep(_: float) -> None:
        raise AssertionError("sleep should not be called for ABORT")

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", fail_sleep)

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        strategy=lambda ctx: 1.0,
        deadline_s=5.0,
        max_attempts=3,
    )

    with pytest.raises(AbortRetryError):
        asyncio.run(policy.call(func, sleep=sleep_fn))


def test_async_policy_sleep_handler_sleeps_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    async def func() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return "ok"

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    def sleep_fn(_: BackoffContext, __: float) -> SleepDecision:
        return SleepDecision.SLEEP

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", record_sleep)

    policy = AsyncRetryPolicy(
        classifier=classifier,
        strategy=lambda ctx: 0.3,
        deadline_s=5.0,
        max_attempts=3,
    )

    result = asyncio.run(policy.call(func, sleep=sleep_fn))
    assert result == "ok"
    assert sleeps == [0.3]


def test_async_sleep_handler_invalid_return_raises() -> None:
    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        strategy=_no_sleep_strategy,
        max_attempts=1,
    )
    state = _state_mod._RetryState(
        policy=policy.retry,
        on_metric=None,
        on_log=None,
        operation=None,
        abort_if=None,
    )
    classification = Classification(klass=ErrorClass.TRANSIENT)
    ctx = _state_mod._build_backoff_context(
        attempt=1,
        classification=classification,
        prev_sleep_s=None,
        remaining_s=1.0,
        cause="exception",
    )
    decision = _state_mod._RetryDecision(action="retry", sleep_s=0.1, context=ctx)

    async def run() -> None:
        with pytest.raises(ValueError, match="sleep handler must return"):
            await _retry_mod._async_sleep_action(
                state=state,
                attempt=1,
                decision=decision,
                sleep_fn=lambda _ctx, _sleep: "nope",
            )

    asyncio.run(run())


def test_async_context_strategy_receives_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    class RateLimitError(Exception):
        pass

    calls = {"n": 0}
    sleep_calls: list[float] = []

    async def func() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitError("429")
        return "ok"

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", fake_sleep)

    def classifier(_: BaseException) -> Classification:
        return Classification(klass=ErrorClass.RATE_LIMIT, retry_after_s=0.25)

    def strategy(ctx: BackoffContext) -> float:
        assert ctx.classification.retry_after_s == 0.25
        return float(ctx.classification.retry_after_s or 0.0)

    policy = AsyncRetryPolicy(
        classifier=classifier,
        strategy=strategy,
        deadline_s=5.0,
        max_attempts=3,
    )

    assert asyncio.run(policy.call(func)) == "ok"
    assert calls["n"] == 2
    assert sleep_calls == [0.25]


@pytest.mark.parametrize("limit, expected_calls", [(0, 1), (1, 2), (2, 3)])
def test_async_per_class_max_attempts_limits_retries(
    monkeypatch: pytest.MonkeyPatch, limit: int, expected_calls: int
) -> None:
    class RateLimitError(Exception):
        pass

    calls = {"n": 0}

    async def func() -> None:
        calls["n"] += 1
        raise RateLimitError("429")

    metric_hook, events = _collect_metrics()

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.RATE_LIMIT

    policy = AsyncRetryPolicy(
        classifier=classifier,
        strategy=_no_sleep_strategy,
        per_class_max_attempts={ErrorClass.RATE_LIMIT: limit},
        max_attempts=10,
    )

    with pytest.raises(RateLimitError):
        asyncio.run(policy.call(func, on_metric=metric_hook))

    assert calls["n"] == expected_calls
    assert events[-1][0] == "max_attempts_exceeded"
    assert events[-1][3]["class"] == ErrorClass.RATE_LIMIT.name
    assert events[-1][3]["stop_reason"] == StopReason.MAX_ATTEMPTS_PER_CLASS.value


def test_async_missing_strategy_stops_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    class TransientError(Exception):
        pass

    calls = {"n": 0}

    async def func() -> None:
        calls["n"] += 1
        raise TransientError("boom")

    metric_hook, events = _collect_metrics()

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", fake_sleep)

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = AsyncRetryPolicy(
        classifier=classifier,
        strategy=None,
        strategies={ErrorClass.RATE_LIMIT: _no_sleep_strategy},
        deadline_s=30.0,
        max_attempts=5,
    )

    with pytest.raises(TransientError):
        asyncio.run(policy.call(func, on_metric=metric_hook))

    assert calls["n"] == 1
    assert sleep_calls == []
    assert events and events[0][0] == "no_strategy_configured"
    assert events[0][3]["class"] == ErrorClass.TRANSIENT.name
    assert events[0][3]["err"] == "TransientError"
    assert events[0][3]["stop_reason"] == StopReason.NO_STRATEGY.value


def test_async_cancelled_error_propagates_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    metric_hook, events = _collect_metrics()
    sleep_calls: list[float] = []
    orig_sleep = asyncio.sleep

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", fake_sleep)

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        strategy=_no_sleep_strategy,
        deadline_s=5.0,
        max_attempts=3,
    )

    async def func() -> str:
        await asyncio.Event().wait()
        return "ok"

    async def run() -> None:
        task = asyncio.create_task(policy.call(func, on_metric=metric_hook))
        await orig_sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.5)

    asyncio.run(run())

    assert events == []
    assert sleep_calls == []


def test_async_deadline_exceeded_reraises_last_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    class SlowError(Exception):
        pass

    fake_time = _FakeTime()

    monkeypatch.setattr(_state_mod.time, "monotonic", fake_time.monotonic)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        fake_time.advance(seconds + 0.01)

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", fake_sleep)

    calls = {"n": 0}

    async def func() -> None:
        calls["n"] += 1
        fake_time.advance(0.2)
        raise SlowError("still failing")

    metric_hook, events = _collect_metrics()

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = AsyncRetryPolicy(
        classifier=classifier,
        strategy=lambda attempt, klass, prev: 10.0,
        deadline_s=1.0,
        max_attempts=5,
    )

    with pytest.raises(SlowError):
        asyncio.run(policy.call(func, on_metric=metric_hook))

    assert calls["n"] == 1
    assert sleep_calls and sleep_calls[0] == pytest.approx(0.8)
    deadline_event = next(event for event in events if event[0] == "deadline_exceeded")
    assert deadline_event[3]["stop_reason"] == StopReason.DEADLINE_EXCEEDED.value


# ---------------------------------------------------------------------------
# Result-based retries
# ---------------------------------------------------------------------------


def test_async_result_classifier_retries_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def func() -> str:
        calls["n"] += 1
        return "retry" if calls["n"] == 1 else "ok"

    def result_classifier(result: str) -> ErrorClass | None:
        return ErrorClass.TRANSIENT if result == "retry" else None

    def strategy(ctx: BackoffContext) -> float:
        assert ctx.cause == "result"
        return 0.0

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        result_classifier=result_classifier,
        strategy=strategy,
        deadline_s=10.0,
        max_attempts=3,
    )

    assert asyncio.run(policy.call(func)) == "ok"
    assert calls["n"] == 2


def test_async_result_classifier_exhausts_with_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def func() -> str:
        return "bad"

    def result_classifier(result: str) -> ErrorClass | None:
        return ErrorClass.TRANSIENT

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        result_classifier=result_classifier,
        strategy=_no_sleep_strategy,
        deadline_s=10.0,
        max_attempts=2,
    )

    with pytest.raises(RetryExhaustedError) as excinfo:
        asyncio.run(policy.call(func))

    err = excinfo.value
    assert err.stop_reason == StopReason.MAX_ATTEMPTS_GLOBAL
    assert err.attempts == 2
    assert err.last_class is ErrorClass.TRANSIENT
    assert err.last_exception is None
    assert err.last_result == "bad"


def test_async_result_classifier_non_retryable_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def func() -> str:
        return "bad"

    def result_classifier(result: str) -> ErrorClass | None:
        return ErrorClass.PERMANENT

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        result_classifier=result_classifier,
        strategy=_no_sleep_strategy,
        deadline_s=10.0,
        max_attempts=3,
    )

    with pytest.raises(RetryExhaustedError) as excinfo:
        asyncio.run(policy.call(func))

    err = excinfo.value
    assert err.stop_reason == StopReason.NON_RETRYABLE_CLASS
    assert err.attempts == 1
    assert err.last_class is ErrorClass.PERMANENT


def test_async_result_classifier_respects_max_unknown_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def func() -> str:
        return "bad"

    def result_classifier(result: str) -> ErrorClass | None:
        return ErrorClass.UNKNOWN

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        result_classifier=result_classifier,
        strategy=_no_sleep_strategy,
        deadline_s=10.0,
        max_attempts=3,
        max_unknown_attempts=0,
    )

    with pytest.raises(RetryExhaustedError) as excinfo:
        asyncio.run(policy.call(func))

    err = excinfo.value
    assert err.stop_reason == StopReason.MAX_UNKNOWN_ATTEMPTS
    assert err.attempts == 1
    assert err.last_class is ErrorClass.UNKNOWN


def test_async_result_classifier_respects_per_class_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def func() -> str:
        return "bad"

    def result_classifier(result: str) -> ErrorClass | None:
        return ErrorClass.RATE_LIMIT

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        result_classifier=result_classifier,
        strategy=_no_sleep_strategy,
        deadline_s=10.0,
        max_attempts=3,
        per_class_max_attempts={ErrorClass.RATE_LIMIT: 0},
    )

    with pytest.raises(RetryExhaustedError) as excinfo:
        asyncio.run(policy.call(func))

    err = excinfo.value
    assert err.stop_reason == StopReason.MAX_ATTEMPTS_PER_CLASS
    assert err.attempts == 1
    assert err.last_class is ErrorClass.RATE_LIMIT


def test_async_result_classifier_mixed_failures_prefer_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FlakyError(Exception):
        pass

    calls = {"n": 0}

    async def func() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise FlakyError("boom")
        return "bad"

    def classifier(exc: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    def result_classifier(result: str) -> ErrorClass | None:
        return ErrorClass.PERMANENT

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    policy = AsyncRetryPolicy(
        classifier=classifier,
        result_classifier=result_classifier,
        strategy=_no_sleep_strategy,
        deadline_s=10.0,
        max_attempts=3,
    )

    with pytest.raises(RetryExhaustedError) as excinfo:
        asyncio.run(policy.call(func))

    err = excinfo.value
    assert err.stop_reason == StopReason.NON_RETRYABLE_CLASS
    assert err.attempts == 2
    assert err.last_class is ErrorClass.PERMANENT
    assert err.last_exception is None
    assert err.last_result == "bad"


def test_async_policy_matches_async_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def classifier(exc: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    def make_flaky() -> tuple[object, dict[str, int]]:
        calls = {"n": 0}

        async def func() -> str:
            calls["n"] += 1
            if calls["n"] < 2:
                raise ValueError("boom")
            return "ok"

        return func, calls

    metric_hook_a, events_a = _collect_metrics()
    func_a, calls_a = make_flaky()
    policy_a = AsyncRetryPolicy(
        classifier=classifier,
        strategy=_no_sleep_strategy,
        deadline_s=10.0,
        max_attempts=3,
    )
    result_a = asyncio.run(policy_a.call(func_a, on_metric=metric_hook_a))

    metric_hook_b, events_b = _collect_metrics()
    func_b, calls_b = make_flaky()
    policy_b = AsyncPolicy(
        retry=AsyncRetry(
            classifier=classifier,
            strategy=_no_sleep_strategy,
            deadline_s=10.0,
            max_attempts=3,
        )
    )
    result_b = asyncio.run(policy_b.call(func_b, on_metric=metric_hook_b))

    assert result_a == result_b == "ok"
    assert calls_a["n"] == calls_b["n"] == 2
    assert events_a == events_b


def test_async_policy_breaker_rejects_when_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    async def func() -> None:
        calls["n"] += 1
        raise RateLimitError("429")

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", noop_sleep)

    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=60.0,
        recovery_timeout_s=30.0,
        trip_on={ErrorClass.TRANSIENT},
    )

    policy = AsyncPolicy(
        retry=AsyncRetry(
            classifier=lambda exc: ErrorClass.TRANSIENT,
            strategy=_no_sleep_strategy,
            max_attempts=1,
        ),
        circuit_breaker=breaker,
    )

    with pytest.raises(RateLimitError):
        asyncio.run(policy.call(func))

    assert calls["n"] == 1


def test_async_policy_breaker_cancelled_records(monkeypatch: pytest.MonkeyPatch) -> None:
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.TRANSIENT},
    )

    called = {"n": 0}
    original = breaker.record_cancel

    def record_cancel() -> None:
        called["n"] += 1
        original()

    breaker.record_cancel = record_cancel  # type: ignore[assignment]

    policy = AsyncPolicy(
        retry=AsyncRetry(
            classifier=lambda exc: ErrorClass.TRANSIENT,
            strategy=_no_sleep_strategy,
            max_attempts=1,
        ),
        circuit_breaker=breaker,
    )

    async def cancelled() -> None:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(policy.call(cancelled))

    assert called["n"] == 1


def test_async_policy_breaker_without_retry_uses_default_classifier() -> None:
    class WeirdError(Exception):
        pass

    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.UNKNOWN},
    )

    policy = AsyncPolicy(circuit_breaker=breaker)

    async def fail() -> None:
        raise WeirdError("boom")

    with pytest.raises(WeirdError):
        asyncio.run(policy.call(fail))

    assert breaker.state is CircuitState.OPEN


def test_async_policy_execute_no_retry_failure_emits_breaker_event() -> None:
    class WeirdError(Exception):
        pass

    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.UNKNOWN},
    )

    policy = AsyncPolicy(circuit_breaker=breaker)
    metric_hook, events = _collect_metrics()

    async def fail() -> None:
        raise WeirdError("boom")

    outcome = asyncio.run(policy.execute(fail, on_metric=metric_hook, operation="op"))

    assert outcome.ok is False
    assert outcome.attempts == 1
    assert isinstance(outcome.last_exception, WeirdError)
    assert outcome.last_class is ErrorClass.UNKNOWN
    assert outcome.cause == "exception"
    assert breaker.state is CircuitState.OPEN

    opened_tags = next(tags for event, _, _, tags in events if event == "circuit_opened")
    assert opened_tags["state"] == CircuitState.OPEN.value
    assert opened_tags["operation"] == "op"


def test_async_policy_execute_breaker_rejected_returns_outcome() -> None:
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=30.0,
        trip_on={ErrorClass.UNKNOWN},
    )
    breaker.record_failure(ErrorClass.UNKNOWN)

    policy = AsyncPolicy(circuit_breaker=breaker)
    metric_hook, events = _collect_metrics()

    async def ok() -> str:
        return "ok"

    outcome = asyncio.run(policy.execute(ok, on_metric=metric_hook, operation="op"))

    assert outcome.ok is False
    assert outcome.attempts == 0
    assert isinstance(outcome.last_exception, CircuitOpenError)
    assert breaker.state is CircuitState.OPEN

    rejected_tags = next(tags for event, _, _, tags in events if event == "circuit_rejected")
    assert rejected_tags["state"] == CircuitState.OPEN.value
    assert rejected_tags["operation"] == "op"


def test_async_policy_execute_with_retry_aborted_records_cancel() -> None:
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.TRANSIENT},
    )

    called = {"n": 0}
    original = breaker.record_cancel

    def record_cancel() -> None:
        called["n"] += 1
        original()

    breaker.record_cancel = record_cancel  # type: ignore[assignment]

    policy = AsyncPolicy(
        retry=AsyncRetry(
            classifier=default_classifier,
            strategy=_no_sleep_strategy,
            max_attempts=3,
        ),
        circuit_breaker=breaker,
    )

    async def ok() -> str:
        return "ok"

    outcome = asyncio.run(policy.execute(ok, abort_if=lambda: True))

    assert outcome.stop_reason is StopReason.ABORTED
    assert outcome.attempts == 0
    assert called["n"] == 1


def test_async_policy_execute_no_retry_success() -> None:
    policy = AsyncPolicy()

    async def ok() -> str:
        return "ok"

    outcome = asyncio.run(policy.execute(ok))

    assert outcome.ok is True
    assert outcome.value == "ok"
    assert outcome.attempts == 1


def test_async_policy_execute_no_retry_abort_if_returns_outcome() -> None:
    policy = AsyncPolicy()

    async def ok() -> str:
        return "ok"

    outcome = asyncio.run(policy.execute(ok, abort_if=lambda: True))

    assert outcome.stop_reason is StopReason.ABORTED
    assert outcome.attempts == 0


def test_async_policy_call_no_retry_abort_if_raises() -> None:
    policy = AsyncPolicy()

    async def ok() -> str:
        return "ok"

    with pytest.raises(AbortRetryError):
        asyncio.run(policy.call(ok, abort_if=lambda: True))


def test_async_policy_call_no_retry_abort_if_records_cancel() -> None:
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
    )
    called = {"n": 0}
    original = breaker.record_cancel

    def record_cancel() -> None:
        called["n"] += 1
        original()

    breaker.record_cancel = record_cancel  # type: ignore[assignment]

    policy = AsyncPolicy(circuit_breaker=breaker)

    async def ok() -> str:
        return "ok"

    with pytest.raises(AbortRetryError):
        asyncio.run(policy.call(ok, abort_if=lambda: True))

    assert called["n"] == 1
