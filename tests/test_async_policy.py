# tests/test_async_policy.py


import asyncio
from typing import Any

import pytest

from redress.classify import default_classifier
from redress.errors import ErrorClass, PermanentError, RateLimitError, StopReason
from redress.policy import AsyncRetryPolicy, MetricHook


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

    monkeypatch.setattr("redress.policy.asyncio.sleep", noop_sleep)

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


def test_async_policy_permanent_error_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def func() -> None:
        calls["n"] += 1
        raise PermanentError("stop")

    metric_hook, events = _collect_metrics()

    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("redress.policy.asyncio.sleep", noop_sleep)

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
    assert event == "permanent_fail"
    assert attempt == 1
    assert sleep_s == 0.0
    assert tags["class"] == ErrorClass.PERMANENT.name


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

    monkeypatch.setattr("redress.policy.asyncio.sleep", noop_sleep)

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

    monkeypatch.setattr("redress.policy.asyncio.sleep", fake_sleep)

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
    assert events[0][3]["stop_reason"] == StopReason.NON_RETRYABLE_CLASS.value


def test_async_cancelled_error_propagates_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    metric_hook, events = _collect_metrics()
    sleep_calls: list[float] = []
    orig_sleep = asyncio.sleep

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("redress.policy.asyncio.sleep", fake_sleep)

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

    monkeypatch.setattr("redress.policy.time.monotonic", fake_time.monotonic)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        fake_time.advance(seconds + 0.01)

    monkeypatch.setattr("redress.policy.asyncio.sleep", fake_sleep)

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
