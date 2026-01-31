import asyncio
import functools
from collections.abc import Callable, Mapping
from typing import cast, overload

from ..budget import Budget
from ..classify import default_classifier
from ..config import ResultClassifierFn
from ..errors import ErrorClass
from ..sleep import (
    AsyncBeforeSleepHook,
    AsyncSleeperFn,
    BeforeSleepHook,
    SleeperFn,
    SleepFn,
)
from ..strategies import StrategyFn, decorrelated_jitter
from .types import AbortPredicate, AttemptHook, ClassifierFn, LogHook, MetricHook, P, T
from .wrappers import AsyncRetryPolicy, RetryPolicy


@overload
def retry(
    func: None = None,
    *,
    classifier: ClassifierFn = ...,
    result_classifier: ResultClassifierFn | None = ...,
    strategy: StrategyFn | None = ...,
    strategies: Mapping[ErrorClass, StrategyFn] | None = ...,
    sleep: SleepFn | None = ...,
    before_sleep: BeforeSleepHook | AsyncBeforeSleepHook | None = ...,
    sleeper: SleeperFn | AsyncSleeperFn | None = ...,
    budget: Budget | None = ...,
    attempt_timeout_s: float | None = ...,
    deadline_s: float = ...,
    max_attempts: int = ...,
    max_unknown_attempts: int | None = ...,
    per_class_max_attempts: Mapping[ErrorClass, int] | None = ...,
    on_metric: MetricHook | None = ...,
    on_log: LogHook | None = ...,
    operation: str | None = ...,
    abort_if: AbortPredicate | None = ...,
    on_attempt_start: AttemptHook | None = ...,
    on_attempt_end: AttemptHook | None = ...,
) -> Callable[[Callable[P, T]], Callable[P, T]]: ...


@overload
def retry(
    func: Callable[P, T],
    *,
    classifier: ClassifierFn = ...,
    result_classifier: ResultClassifierFn | None = ...,
    strategy: StrategyFn | None = ...,
    strategies: Mapping[ErrorClass, StrategyFn] | None = ...,
    sleep: SleepFn | None = ...,
    before_sleep: BeforeSleepHook | AsyncBeforeSleepHook | None = ...,
    sleeper: SleeperFn | AsyncSleeperFn | None = ...,
    budget: Budget | None = ...,
    attempt_timeout_s: float | None = ...,
    deadline_s: float = ...,
    max_attempts: int = ...,
    max_unknown_attempts: int | None = ...,
    per_class_max_attempts: Mapping[ErrorClass, int] | None = ...,
    on_metric: MetricHook | None = ...,
    on_log: LogHook | None = ...,
    operation: str | None = ...,
    abort_if: AbortPredicate | None = ...,
    on_attempt_start: AttemptHook | None = ...,
    on_attempt_end: AttemptHook | None = ...,
) -> Callable[P, T]: ...


def retry(
    func: Callable[P, T] | None = None,
    *,
    classifier: ClassifierFn = default_classifier,
    result_classifier: ResultClassifierFn | None = None,
    strategy: StrategyFn | None = None,
    strategies: Mapping[ErrorClass, StrategyFn] | None = None,
    sleep: SleepFn | None = None,
    before_sleep: BeforeSleepHook | AsyncBeforeSleepHook | None = None,
    sleeper: SleeperFn | AsyncSleeperFn | None = None,
    budget: Budget | None = None,
    attempt_timeout_s: float | None = None,
    deadline_s: float = 60.0,
    max_attempts: int = 6,
    max_unknown_attempts: int | None = 2,
    per_class_max_attempts: Mapping[ErrorClass, int] | None = None,
    on_metric: MetricHook | None = None,
    on_log: LogHook | None = None,
    operation: str | None = None,
    abort_if: AbortPredicate | None = None,
    on_attempt_start: AttemptHook | None = None,
    on_attempt_end: AttemptHook | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]] | Callable[P, T]:
    """
    Decorator that wraps a function in a RetryPolicy (sync) or AsyncRetryPolicy (async).

    Usage
    -----
        @retry(classifier=default_classifier, strategy=decorrelated_jitter())
        def fetch_user() -> str:
            ...

    Parameters mirror RetryPolicy/AsyncRetryPolicy (including result_classifier).
    Hooks/operation can be set up-front (including on_attempt_start/on_attempt_end).

    If neither `strategy` nor `strategies` is provided, a default
    decorrelated_jitter(max_s=5.0) strategy is injected.

    abort_if can be used to cooperatively stop retry execution.
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        op_name = operation or getattr(func, "__name__", None)
        effective_strategy: StrategyFn | None
        if strategy is None and strategies is None:
            effective_strategy = decorrelated_jitter(max_s=5.0)
        else:
            effective_strategy = strategy

        if asyncio.iscoroutinefunction(func):
            async_policy = AsyncRetryPolicy(
                classifier=classifier,
                result_classifier=result_classifier,
                strategy=effective_strategy,
                strategies=strategies,
                sleep=sleep,
                before_sleep=before_sleep,
                sleeper=sleeper,
                budget=budget,
                attempt_timeout_s=attempt_timeout_s,
                deadline_s=deadline_s,
                max_attempts=max_attempts,
                max_unknown_attempts=max_unknown_attempts,
                per_class_max_attempts=per_class_max_attempts,
            )

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                result = await async_policy.call(
                    lambda: func(*args, **kwargs),
                    on_metric=on_metric,
                    on_log=on_log,
                    operation=op_name,
                    abort_if=abort_if,
                    on_attempt_start=on_attempt_start,
                    on_attempt_end=on_attempt_end,
                )
                return cast(T, result)

            return async_wrapper  # type: ignore[return-value]

        policy = RetryPolicy(
            classifier=classifier,
            result_classifier=result_classifier,
            strategy=effective_strategy,
            strategies=strategies,
            sleep=sleep,
            before_sleep=cast(BeforeSleepHook | None, before_sleep),
            sleeper=cast(SleeperFn | None, sleeper),
            budget=budget,
            attempt_timeout_s=attempt_timeout_s,
            deadline_s=deadline_s,
            max_attempts=max_attempts,
            max_unknown_attempts=max_unknown_attempts,
            per_class_max_attempts=per_class_max_attempts,
        )

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            result = policy.call(
                lambda: func(*args, **kwargs),
                on_metric=on_metric,
                on_log=on_log,
                operation=op_name,
                abort_if=abort_if,
                on_attempt_start=on_attempt_start,
                on_attempt_end=on_attempt_end,
            )
            return cast(T, result)

        return wrapper

    if func is not None:
        return decorator(func)

    return decorator
