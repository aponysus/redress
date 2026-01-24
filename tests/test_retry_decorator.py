# tests/test_retry_decorator.py


import asyncio
import importlib

import pytest

from redress import retry
from redress.errors import ErrorClass, RateLimitError

_retry_mod = importlib.import_module("redress.policy.retry")


def _no_sleep_strategy(_: int, __: ErrorClass, ___: float | None) -> float:
    return 0.0


def test_retry_decorator_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)
    events: list[tuple[str, int, float, dict[str, str]]] = []
    calls = {"n": 0}

    def metric(event: str, attempt: int, sleep_s: float, tags: dict[str, str]) -> None:
        events.append((event, attempt, sleep_s, tags))

    @retry(
        classifier=lambda exc: ErrorClass.TRANSIENT,
        strategy=_no_sleep_strategy,
        on_metric=metric,
    )
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitError("retry me")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 2

    retry_event = next(e for e in events if e[0] == "retry")
    assert retry_event[1] == 1  # attempt number
    assert retry_event[3]["class"] == ErrorClass.TRANSIENT.name
    assert retry_event[3]["operation"] == "flaky"

    success_event = next(e for e in events if e[0] == "success")
    assert success_event[3]["operation"] == "flaky"


def test_retry_decorator_async(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(_retry_mod.asyncio, "sleep", fake_sleep)
    events: list[tuple[str, int, float, dict[str, str]]] = []
    calls = {"n": 0}

    def metric(event: str, attempt: int, sleep_s: float, tags: dict[str, str]) -> None:
        events.append((event, attempt, sleep_s, tags))

    @retry(
        classifier=lambda exc: ErrorClass.TRANSIENT,
        strategy=_no_sleep_strategy,
        on_metric=metric,
    )
    async def flaky_async() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitError("retry me")
        return "async-ok"

    assert asyncio.run(flaky_async()) == "async-ok"
    assert calls["n"] == 2
    assert sleep_calls == [0.0]

    retry_event = next(e for e in events if e[0] == "retry")
    assert retry_event[3]["operation"] == "flaky_async"
    assert retry_event[3]["class"] == ErrorClass.TRANSIENT.name

    success_event = next(e for e in events if e[0] == "success")
    assert success_event[3]["operation"] == "flaky_async"


def test_retry_decorator_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)
    calls = {"n": 0}

    @retry
    def flaky_default() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitError("retry me")
        return "ok"

    assert flaky_default() == "ok"
    assert calls["n"] == 2


def test_retry_decorator_respects_strategy_mapping_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)
    calls = {"n": 0}

    @retry(
        classifier=lambda exc: ErrorClass.TRANSIENT,
        strategy=None,
        strategies={ErrorClass.RATE_LIMIT: _no_sleep_strategy},
        max_attempts=3,
    )
    def flaky() -> str:
        calls["n"] += 1
        raise RateLimitError("retry me")

    with pytest.raises(RateLimitError):
        flaky()

    # No fallback strategy should be injected for TRANSIENT.
    assert calls["n"] == 1
