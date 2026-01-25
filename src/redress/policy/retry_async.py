from collections.abc import Awaitable, Callable, Mapping

from ..config import ResultClassifierFn, RetryConfig
from ..errors import ErrorClass
from ..sleep import SleepFn
from ..strategies import StrategyFn
from .base import _BaseRetryPolicy
from .context import _AsyncRetryContext
from .retry_helpers import _resolve_attempt_hooks, _resolve_sleep
from .runner import run_async_call, run_async_execute
from .types import (
    AbortPredicate,
    AttemptHook,
    ClassifierFn,
    LogHook,
    MetricHook,
    RetryOutcome,
    RetryTimeline,
    T,
)


class AsyncRetry(_BaseRetryPolicy):
    """
    Async retry loop mirroring Retry semantics for awaitables.
    """

    def __init__(
        self,
        *,
        classifier: ClassifierFn,
        result_classifier: ResultClassifierFn | None = None,
        strategy: StrategyFn | None = None,
        strategies: Mapping[ErrorClass, StrategyFn] | None = None,
        sleep: SleepFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
        deadline_s: float = 60.0,
        max_attempts: int = 6,
        max_unknown_attempts: int | None = 2,
        per_class_max_attempts: Mapping[ErrorClass, int] | None = None,
    ) -> None:
        super().__init__(
            classifier=classifier,
            result_classifier=result_classifier,
            strategy=strategy,
            strategies=strategies,
            sleep=sleep,
            deadline_s=deadline_s,
            max_attempts=max_attempts,
            max_unknown_attempts=max_unknown_attempts,
            per_class_max_attempts=per_class_max_attempts,
        )
        self.on_attempt_start = on_attempt_start
        self.on_attempt_end = on_attempt_end

    @classmethod
    def from_config(
        cls,
        config: RetryConfig,
        *,
        classifier: ClassifierFn,
    ) -> "AsyncRetry":
        """
        Construct an AsyncRetry from a RetryConfig bundle.
        """
        return cls(
            classifier=classifier,
            result_classifier=config.result_classifier,
            strategy=config.default_strategy,
            strategies=config.class_strategies,
            sleep=config.sleep,
            deadline_s=config.deadline_s,
            max_attempts=config.max_attempts,
            max_unknown_attempts=config.max_unknown_attempts,
            per_class_max_attempts=config.per_class_max_attempts,
        )

    async def call(
        self,
        func: Callable[[], Awaitable[T]],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
        sleep: SleepFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
    ) -> T:
        """
        Execute an async function with retries according to this policy.

        Result-based failures raise RetryExhaustedError when retries stop.
        abort_if can be used to cooperatively stop retry execution.
        sleep can defer or abort backoff based on the BackoffContext.
        """
        sleep_fn = _resolve_sleep(self.sleep, sleep)
        attempt_start_hook, attempt_end_hook = _resolve_attempt_hooks(
            policy_start=self.on_attempt_start,
            policy_end=self.on_attempt_end,
            call_start=on_attempt_start,
            call_end=on_attempt_end,
        )
        return await run_async_call(
            policy=self,
            func=func,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
            abort_if=abort_if,
            sleep_fn=sleep_fn,
            attempt_start_hook=attempt_start_hook,
            attempt_end_hook=attempt_end_hook,
        )

    async def execute(
        self,
        func: Callable[[], Awaitable[T]],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
        sleep: SleepFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
        capture_timeline: bool | RetryTimeline | None = None,
    ) -> RetryOutcome[T]:
        """
        Execute `func` and return a structured RetryOutcome.
        """
        sleep_fn = _resolve_sleep(self.sleep, sleep)
        attempt_start_hook, attempt_end_hook = _resolve_attempt_hooks(
            policy_start=self.on_attempt_start,
            policy_end=self.on_attempt_end,
            call_start=on_attempt_start,
            call_end=on_attempt_end,
        )
        return await run_async_execute(
            policy=self,
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

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
        sleep: SleepFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
    ) -> _AsyncRetryContext:
        """
        Async context manager that binds hooks/operation for multiple calls.
        """
        return _AsyncRetryContext(
            self,
            on_metric,
            on_log,
            operation,
            abort_if,
            sleep,
            on_attempt_start,
            on_attempt_end,
        )
