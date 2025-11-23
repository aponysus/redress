# tests/test_strategies.py

from __future__ import annotations

import random

from reflexio.errors import ErrorClass
from reflexio.strategies import decorrelated_jitter, equal_jitter, token_backoff


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
