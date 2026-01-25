from collections.abc import Callable, Mapping
from typing import Any

from ..config import ResultClassifierFn, RetryConfig
from ..errors import ErrorClass
from ..sleep import SleepFn
from ..strategies import StrategyFn
from .base import _BaseRetryPolicy
from .context import _RetryContext
from .retry_helpers import _resolve_attempt_hooks, _resolve_sleep
from .runner import run_sync_call, run_sync_execute
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


class Retry(_BaseRetryPolicy):
    """
    Retry component with classification + backoff strategies.

    The policy itself is deliberately dumb:
      * It does not know about HTTP, SQL, Kafka, etc.
      * It only understands ErrorClass values and which strategy to use for each.
      * All domain logic lives in your classifier and strategy functions.

    Parameters
    ----------
    classifier:
        Function mapping an exception to an ErrorClass or a Classification.

    result_classifier:
        Optional function mapping a return value to None (success) or to an
        ErrorClass/Classification that should be retried.

    strategy:
        Optional default backoff strategy to use for *all* error classes
        that are not explicitly configured in `strategies`. This keeps the
        old "single strategy" usage working:

            Retry(
                classifier=default_classifier,
                strategy=decorrelated_jitter(),
                ...
            )

    strategies:
        Optional mapping from ErrorClass -> StrategyFn. Strategies may use the
        legacy `(attempt, klass, prev_sleep_s)` signature or the context-aware
        `(ctx: BackoffContext)` signature. If provided, per-class strategies
        override `strategy` for those specific classes.

        Example:

            strategies = {
                ErrorClass.CONCURRENCY: decorrelated_jitter(max_s=1.0),
                ErrorClass.RATE_LIMIT:  decorrelated_jitter(max_s=60.0),
                ErrorClass.SERVER_ERROR: equal_jitter(),
            }

    deadline_s:
        Total wall-clock time (in seconds) allowed across all attempts.

    max_attempts:
        Hard cap on how many attempts will be made, regardless of deadline.

    max_unknown_attempts:
        Optional special cap for ErrorClass.UNKNOWN. If exceeded, the last
        exception is re-raised with its original traceback even if the
        global max_attempts is not yet hit.

    Notes
    -----
    * PERMANENT errors are never retried.
    * UNKNOWN errors default to being retried like TRANSIENT, but with an
      optional dedicated cap via max_unknown_attempts.
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
    ) -> "Retry":
        """
        Construct a Retry from a RetryConfig bundle.
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

    def call(
        self,
        func: Callable[[], Any],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
        sleep: SleepFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
    ) -> Any:
        """
        Execute `func` with retries according to this policy.

        Parameters
        ----------
        func:
            Zero-argument callable to invoke. All exceptions are intercepted
            and handled according to `classifier` and the configured backoff
            strategies.

        on_metric:
            Optional callback for observability. Signature:

                on_metric(
                    event: str,          # event name, see below
                    attempt: int,        # 1-based attempt number being executed
                    sleep_s: float,      # scheduled delay for retries, else 0.0
                    tags: Dict[str, Any],# safe tags (no payloads/messages)
                )

            Events emitted:
              * "success"              – func() returned successfully
              * "permanent_fail"       – PERMANENT/AUTH/PERMISSION classes, no retry
              * "deadline_exceeded"    – wall-clock deadline exceeded
              * "retry"                – a retry is scheduled
              * "no_strategy_configured" – missing strategy for a retryable class
              * "max_attempts_exceeded"– we hit max_attempts and re-raise with
                the original traceback
              * "max_unknown_attempts_exceeded" – UNKNOWN cap hit

            Default tags:
              * class – ErrorClass.name when available
              * err   – exception class name when an exception exists
              * stop_reason – terminal reason (only on terminal events)
              * operation – optional logical operation name from `operation`

            Hook errors are swallowed (best-effort) so user workloads are never
            interrupted by observability failures.

        on_log:
            Optional logging hook, invoked at the same points as on_metric.
            Signature:

                on_log(event: str, fields: Dict[str, Any]) -> None

            The fields dict includes attempt, sleep_s, and the same tags as
            on_metric. Errors are swallowed for the same reason as on_metric.

        operation:
            Optional logical name for the action being retried (e.g.,
            "fetch_user_profile"). Propagated into tags for metrics/logging.

        abort_if:
            Optional predicate checked before attempts and before sleeping.
            When it returns True, retries stop immediately and AbortRetryError
            is raised.

        sleep:
            Optional handler that can sleep, defer, or abort retry backoff
            based on the BackoffContext and proposed sleep duration.

        Returns
        -------
        Any
            The return value of func() if it eventually succeeds.

        Raises
        ------
        BaseException
            The original exception from the last attempt, re-raised with
            its original traceback after retries are exhausted or a
            non-retriable condition is hit.

        RetryExhaustedError
            Raised when retries stop due to a result-based failure (no
            exception was thrown).

        AbortRetryError
            Raised when abort_if returns True or the user raises AbortRetryError.
        """
        sleep_fn = _resolve_sleep(self.sleep, sleep)
        attempt_start_hook, attempt_end_hook = _resolve_attempt_hooks(
            policy_start=self.on_attempt_start,
            policy_end=self.on_attempt_end,
            call_start=on_attempt_start,
            call_end=on_attempt_end,
        )
        return run_sync_call(
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

    def execute(
        self,
        func: Callable[[], T],
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
        return run_sync_execute(
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
    ) -> _RetryContext:
        """
        Context manager that binds hooks/operation for multiple calls.

        Usage:
            with policy.context(on_metric=hook, operation="batch") as retry:
                retry(fn1)
                retry(fn2, arg1, arg2)
        """
        return _RetryContext(
            self,
            on_metric,
            on_log,
            operation,
            abort_if,
            sleep,
            on_attempt_start,
            on_attempt_end,
        )
