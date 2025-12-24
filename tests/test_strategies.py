# tests/test_strategies.py


import random

import hypothesis.strategies as st
from hypothesis import given

import redress.strategies as strategies
from redress.errors import ErrorClass
from redress.strategies import decorrelated_jitter, equal_jitter, token_backoff


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
