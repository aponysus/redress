from collections.abc import Callable
from typing import Any

from ...sleep import BeforeSleepHook, SleeperFn, SleepFn
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
from .sync_core import _run_sync_call, _run_sync_execute


def run_sync_call(
    *,
    policy: _BaseRetryPolicy,
    func: Callable[[], Any],
    on_metric: MetricHook | None,
    on_log: LogHook | None,
    operation: str | None,
    abort_if: AbortPredicate | None,
    sleep_fn: SleepFn | None,
    before_sleep: BeforeSleepHook | None,
    sleeper: SleeperFn | None,
    attempt_start_hook: AttemptHook | None,
    attempt_end_hook: AttemptHook | None,
) -> Any:
    return _run_sync_call(
        policy=policy,
        func=func,
        on_metric=on_metric,
        on_log=on_log,
        operation=operation,
        abort_if=abort_if,
        sleep_fn=sleep_fn,
        before_sleep=before_sleep,
        sleeper=sleeper,
        attempt_start_hook=attempt_start_hook,
        attempt_end_hook=attempt_end_hook,
    )


def run_sync_execute(
    *,
    policy: _BaseRetryPolicy,
    func: Callable[[], T],
    on_metric: MetricHook | None,
    on_log: LogHook | None,
    operation: str | None,
    abort_if: AbortPredicate | None,
    sleep_fn: SleepFn | None,
    before_sleep: BeforeSleepHook | None,
    sleeper: SleeperFn | None,
    attempt_start_hook: AttemptHook | None,
    attempt_end_hook: AttemptHook | None,
    capture_timeline: bool | RetryTimeline | None,
) -> RetryOutcome[T]:
    return _run_sync_execute(
        policy=policy,
        func=func,
        on_metric=on_metric,
        on_log=on_log,
        operation=operation,
        abort_if=abort_if,
        sleep_fn=sleep_fn,
        before_sleep=before_sleep,
        sleeper=sleeper,
        attempt_start_hook=attempt_start_hook,
        attempt_end_hook=attempt_end_hook,
        capture_timeline=capture_timeline,
    )
