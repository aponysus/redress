import inspect
import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast

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


def _normalize_strategy(strategy: StrategyFn) -> BackoffFn:
    try:
        signature = inspect.signature(strategy)
    except (TypeError, ValueError) as exc:
        raise TypeError("Strategy must accept (ctx) or (attempt, klass, prev_sleep_s)") from exc

    required_positional = [
        p
        for p in signature.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and p.default is inspect.Parameter.empty
    ]
    required_kwonly = [
        p
        for p in signature.parameters.values()
        if p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is inspect.Parameter.empty
    ]

    if required_kwonly:
        raise TypeError("Strategy must accept (ctx) or (attempt, klass, prev_sleep_s)")

    if len(required_positional) == 1:
        return cast(ContextStrategyFn, strategy)

    if len(required_positional) == 3:
        legacy = cast(LegacyStrategyFn, strategy)

        def wrapped(ctx: BackoffContext) -> float:
            return legacy(ctx.attempt, ctx.klass, ctx.prev_sleep_s)

        return wrapped

    raise TypeError("Strategy must accept (ctx) or (attempt, klass, prev_sleep_s)")


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


def retry_after_or(
    fallback: StrategyFn,
    *,
    jitter_s: float = 0.25,
) -> StrategyFn:
    """
    Honor Classification.retry_after_s when present, otherwise defer to fallback.
    """
    fallback_fn = _normalize_strategy(fallback)
    jitter = max(0.0, jitter_s)

    def f(ctx: BackoffContext) -> float:
        retry_after = ctx.classification.retry_after_s
        if retry_after is not None and math.isfinite(retry_after):
            sleep_s = max(0.0, float(retry_after))
            if jitter:
                sleep_s += random.uniform(0.0, jitter)
        else:
            sleep_s = fallback_fn(ctx)

        if not math.isfinite(sleep_s):
            sleep_s = 0.0

        sleep_s = max(0.0, sleep_s)
        if ctx.remaining_s is not None:
            sleep_s = min(sleep_s, ctx.remaining_s)
        return sleep_s

    return f
