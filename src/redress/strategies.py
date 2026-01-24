import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .classify import Classification
from .errors import ErrorClass


@dataclass(frozen=True)
class BackoffContext:
    attempt: int
    classification: Classification
    prev_sleep_s: float | None
    remaining_s: float | None
    cause: Literal["exception", "result"]

    @property
    def klass(self) -> ErrorClass:
        return self.classification.klass


LegacyStrategyFn = Callable[[int, ErrorClass, float | None], float]
ContextStrategyFn = Callable[[BackoffContext], float]
StrategyFn = LegacyStrategyFn | ContextStrategyFn
BackoffFn = ContextStrategyFn


def decorrelated_jitter(base_s: float = 0.25, max_s: float = 30.0) -> StrategyFn:
    """
    Decorrelated jitter backoff.

    See: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/

    Sleep is chosen uniformly from [base_s, prev_sleep * 3], clamped to max_s.
    """

    def f(attempt: int, klass: ErrorClass, prev_sleep: float | None) -> float:
        prev = prev_sleep or base_s
        return min(max_s, random.uniform(base_s, prev * 3.0))

    return f


def equal_jitter(base_s: float = 0.25, max_s: float = 30.0) -> StrategyFn:
    """
    Equal-jitter exponential backoff.

    cap = min(max_s, base_s * 2^attempt)
    sleep in [cap/2, cap]
    """

    def f(attempt: int, klass: ErrorClass, prev_sleep: float | None) -> float:
        cap = min(max_s, base_s * (2.0**attempt))
        return cap / 2.0 + random.uniform(0.0, cap / 2.0)

    return f


def token_backoff(base_s: float = 0.25, max_s: float = 20.0) -> StrategyFn:
    """
    Slightly gentler exponential backoff (1.5^attempt) with jitter.

    Good for token / credit based systems where you want to be responsive
    but not hammer the service.
    """

    def f(attempt: int, klass: ErrorClass, prev_sleep: float | None) -> float:
        cap = min(max_s, base_s * (1.5**attempt))
        return random.uniform(cap / 2.0, cap)

    return f
