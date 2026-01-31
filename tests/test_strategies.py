# tests/test_strategies.py


import random

import hypothesis.strategies as st
import pytest
from hypothesis import given

import redress.strategies as strategies
from redress.classify import Classification
from redress.errors import ErrorClass
from redress.strategies import (
    BackoffContext,
    adaptive,
    decorrelated_jitter,
    equal_jitter,
    retry_after_or,
    token_backoff,
)


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_decorrelated_jitter_bounds() -> None:
    random.seed(0)
    strat = decorrelated_jitter(base_s=0.25, max_s=5.0)
    prev = None
    for attempt in range(1, 10):
        sleep_s = strat(attempt, ErrorClass.TRANSIENT, prev)
        assert 0.0 <= sleep_s <= 5.0
        prev = sleep_s


def test_equal_jitter_bounds() -> None:
    random.seed(1)
    strat = equal_jitter(base_s=0.5, max_s=4.0)
    prev = None
    for attempt in range(1, 10):
        sleep_s = strat(attempt, ErrorClass.SERVER_ERROR, prev)
        assert 0.0 <= sleep_s <= 4.0
        prev = sleep_s


def test_token_backoff_bounds() -> None:
    random.seed(2)
    strat = token_backoff(base_s=0.5, max_s=3.0)
    prev = None
    for attempt in range(1, 10):
        sleep_s = strat(attempt, ErrorClass.RATE_LIMIT, prev)
        assert 0.0 <= sleep_s <= 3.0
        prev = sleep_s


def test_adaptive_strategy_scales_up() -> None:
    clock = _FakeClock()
    strat = adaptive(
        lambda ctx: 1.0,
        window_s=60.0,
        target_success=0.8,
        max_multiplier=3.0,
        clock=clock.monotonic,
    )

    strat.record_failure()
    strat.record_failure()

    ctx = BackoffContext(
        attempt=1,
        classification=Classification(ErrorClass.TRANSIENT),
        prev_sleep_s=None,
        remaining_s=None,
        cause="exception",
    )

    assert strat(ctx) == 3.0


def test_adaptive_strategy_resets_with_successes() -> None:
    clock = _FakeClock()
    strat = adaptive(
        lambda ctx: 1.0,
        window_s=60.0,
        target_success=0.8,
        max_multiplier=3.0,
        clock=clock.monotonic,
    )

    strat.record_failure()
    for _ in range(4):
        strat.record_success()

    ctx = BackoffContext(
        attempt=1,
        classification=Classification(ErrorClass.TRANSIENT),
        prev_sleep_s=None,
        remaining_s=None,
        cause="exception",
    )

    assert strat(ctx) == pytest.approx(1.0)


def test_adaptive_strategy_prunes_window() -> None:
    clock = _FakeClock()
    strat = adaptive(
        lambda ctx: 1.0,
        window_s=5.0,
        target_success=0.9,
        max_multiplier=4.0,
        clock=clock.monotonic,
    )

    strat.record_failure()
    clock.advance(10.0)
    strat.record_success()

    ctx = BackoffContext(
        attempt=1,
        classification=Classification(ErrorClass.TRANSIENT),
        prev_sleep_s=None,
        remaining_s=None,
        cause="exception",
    )

    assert strat(ctx) == 1.0


@given(
    base_s=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    max_s=st.floats(min_value=0.05, max_value=10.0, allow_nan=False, allow_infinity=False),
    prev=st.one_of(st.none(), st.floats(min_value=0.0, max_value=10.0, allow_nan=False)),
    attempt=st.integers(min_value=1, max_value=6),
)
def test_decorrelated_jitter_property(
    base_s: float, max_s: float, prev: float | None, attempt: int
) -> None:
    max_s = max(max_s, base_s)  # ensure max >= base
    original_uniform = strategies.random.uniform
    try:
        strategies.random.uniform = lambda a, b: (a + b) / 2.0
        strat = decorrelated_jitter(base_s=base_s, max_s=max_s)
        sleep_s = strat(attempt, ErrorClass.TRANSIENT, prev)
        effective_prev = prev if (prev is not None and prev > 0.0) else base_s
        a, b = base_s, effective_prev * 3.0
        low = min(a, b)
        high = min(max_s, max(a, b))
        assert low <= sleep_s <= high
    finally:
        strategies.random.uniform = original_uniform


@given(
    base_s=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    max_s=st.floats(min_value=0.05, max_value=10.0, allow_nan=False, allow_infinity=False),
    attempt=st.integers(min_value=1, max_value=8),
)
def test_equal_jitter_property(base_s: float, max_s: float, attempt: int) -> None:
    max_s = max(max_s, base_s)
    original_uniform = strategies.random.uniform
    try:
        strategies.random.uniform = lambda a, b: (a + b) / 2.0
        strat = equal_jitter(base_s=base_s, max_s=max_s)
        cap = min(max_s, base_s * (2.0**attempt))
        sleep_s = strat(attempt, ErrorClass.SERVER_ERROR, None)
        assert cap / 2.0 <= sleep_s <= cap
    finally:
        strategies.random.uniform = original_uniform


@given(
    base_s=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    max_s=st.floats(min_value=0.05, max_value=10.0, allow_nan=False, allow_infinity=False),
    attempt=st.integers(min_value=1, max_value=8),
)
def test_token_backoff_property(base_s: float, max_s: float, attempt: int) -> None:
    max_s = max(max_s, base_s)
    original_uniform = strategies.random.uniform
    try:
        strategies.random.uniform = lambda a, b: (a + b) / 2.0
        strat = token_backoff(base_s=base_s, max_s=max_s)
        cap = min(max_s, base_s * (1.5**attempt))
        sleep_s = strat(attempt, ErrorClass.RATE_LIMIT, None)
        assert cap / 2.0 <= sleep_s <= cap
    finally:
        strategies.random.uniform = original_uniform


def test_retry_after_or_uses_retry_after() -> None:
    calls = {"n": 0}

    def fallback(attempt: int, klass: ErrorClass, prev_sleep: float | None) -> float:
        calls["n"] += 1
        return 1.0

    strat = retry_after_or(fallback, jitter_s=0.0)
    ctx = BackoffContext(
        attempt=1,
        classification=Classification(klass=ErrorClass.RATE_LIMIT, retry_after_s=2.0),
        prev_sleep_s=None,
        remaining_s=10.0,
        cause="exception",
    )
    assert strat(ctx) == 2.0
    assert calls["n"] == 0


def test_retry_after_or_falls_back() -> None:
    calls = {"n": 0}

    def fallback(attempt: int, klass: ErrorClass, prev_sleep: float | None) -> float:
        calls["n"] += 1
        return 1.5

    strat = retry_after_or(fallback, jitter_s=0.0)
    ctx = BackoffContext(
        attempt=1,
        classification=Classification(klass=ErrorClass.TRANSIENT),
        prev_sleep_s=None,
        remaining_s=10.0,
        cause="exception",
    )
    assert strat(ctx) == 1.5
    assert calls["n"] == 1


def test_retry_after_or_clamps_remaining() -> None:
    def fallback(attempt: int, klass: ErrorClass, prev_sleep: float | None) -> float:
        return 10.0

    strat = retry_after_or(fallback, jitter_s=0.0)
    ctx = BackoffContext(
        attempt=1,
        classification=Classification(klass=ErrorClass.RATE_LIMIT, retry_after_s=5.0),
        prev_sleep_s=None,
        remaining_s=1.0,
        cause="exception",
    )
    assert strat(ctx) == 1.0

    ctx_fallback = BackoffContext(
        attempt=1,
        classification=Classification(klass=ErrorClass.TRANSIENT),
        prev_sleep_s=None,
        remaining_s=0.5,
        cause="exception",
    )
    assert strat(ctx_fallback) == 0.5


def test_retry_after_or_works_with_result_cause() -> None:
    def fallback(attempt: int, klass: ErrorClass, prev_sleep: float | None) -> float:
        return 1.0

    strat = retry_after_or(fallback, jitter_s=0.0)
    ctx = BackoffContext(
        attempt=1,
        classification=Classification(klass=ErrorClass.RATE_LIMIT, retry_after_s=2.0),
        prev_sleep_s=None,
        remaining_s=10.0,
        cause="result",
    )
    assert strat(ctx) == 2.0
