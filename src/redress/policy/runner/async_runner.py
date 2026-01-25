from collections.abc import Awaitable, Callable

from ...sleep import SleepFn
from ..base import _BaseRetryPolicy
from ..types import (
    AbortPredicate,
    AttemptHook,
    LogHook,
    MetricHook,
    RetryOutcome,
    RetryTimeline,
    T,
)
from .async_core import _run_async_call, _run_async_execute


async def run_async_call(
    *,
    policy: _BaseRetryPolicy,
    func: Callable[[], Awaitable[T]],
    on_metric: MetricHook | None,
    on_log: LogHook | None,
    operation: str | None,
    abort_if: AbortPredicate | None,
    sleep_fn: SleepFn | None,
    attempt_start_hook: AttemptHook | None,
    attempt_end_hook: AttemptHook | None,
) -> T:
    return await _run_async_call(
        policy=policy,
        func=func,
        on_metric=on_metric,
        on_log=on_log,
        operation=operation,
        abort_if=abort_if,
        sleep_fn=sleep_fn,
        attempt_start_hook=attempt_start_hook,
        attempt_end_hook=attempt_end_hook,
    )


async def run_async_execute(
    *,
    policy: _BaseRetryPolicy,
    func: Callable[[], Awaitable[T]],
    on_metric: MetricHook | None,
    on_log: LogHook | None,
    operation: str | None,
    abort_if: AbortPredicate | None,
    sleep_fn: SleepFn | None,
    attempt_start_hook: AttemptHook | None,
    attempt_end_hook: AttemptHook | None,
    capture_timeline: bool | RetryTimeline | None,
) -> RetryOutcome[T]:
    return await _run_async_execute(
        policy=policy,
        func=func,
        on_metric=on_metric,
        on_log=on_log,
        operation=operation,
        abort_if=abort_if,
        sleep_fn=sleep_fn,
        attempt_start_hook=attempt_start_hook,
        attempt_end_hook=attempt_end_hook,
        capture_timeline=capture_timeline,
    )
