# tests/test_async_policy.py


import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from redress.classify import default_classifier
from redress.errors import ErrorClass, PermanentError, RateLimitError
from redress.policy import AsyncRetryPolicy, MetricHook


def _collect_metrics() -> tuple[MetricHook, list[tuple[str, int, float, dict[str, Any]]]]:
    events: list[tuple[str, int, float, dict[str, Any]]] = []

    def hook(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        events.append((event, attempt, sleep_s, tags))

    return hook, events


def _no_sleep_strategy(_: int, __: ErrorClass, ___: float | None) -> float:
    return 0.0


class _FakeTime:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


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


def test_async_deadline_exceeded_reraises_last_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    class SlowError(Exception):
        pass

    fake_time = _FakeTime()

    def fake_now(_: Any = None) -> datetime:
        return fake_time.now()

    monkeypatch.setattr(
        "redress.policy.datetime", type("DT", (), {"now": staticmethod(fake_now), "UTC": UTC})
    )

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
    assert "deadline_exceeded" in [event[0] for event in events]
