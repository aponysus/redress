import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ..config import ResultClassifierFn, RetryConfig
from ..errors import ErrorClass, RetryExhaustedError, StopReason
from ..strategies import StrategyFn
from .base import _BaseRetryPolicy, _normalize_classification
from .context import _AsyncRetryContext, _RetryContext
from .state import _RetryState
from .types import ClassifierFn, LogHook, MetricHook, T


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
            deadline_s=deadline_s,
            max_attempts=max_attempts,
            max_unknown_attempts=max_unknown_attempts,
            per_class_max_attempts=per_class_max_attempts,
        )

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
        """
        state = _RetryState(
            policy=self,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
        )

        for attempt in range(1, self.max_attempts + 1):
            try:
                result = func()
                if self.result_classifier is None:
                    state.emit("success", attempt, 0.0)
                    return result

                classification_result = self.result_classifier(result)
                if classification_result is None:
                    state.emit("success", attempt, 0.0)
                    return result

                classification = _normalize_classification(classification_result)
                decision = state.handle_result(result, classification, attempt)
                if decision.action == "raise":
                    stop_reason = state.last_stop_reason or StopReason.MAX_ATTEMPTS_GLOBAL
                    raise RetryExhaustedError(
                        stop_reason=stop_reason,
                        attempts=attempt,
                        last_class=state.last_class,
                        last_exception=None,
                        last_result=state.last_result,
                    )

                time.sleep(decision.sleep_s)

                if state.elapsed() > self.deadline:
                    state.last_stop_reason = StopReason.DEADLINE_EXCEEDED
                    state.emit(
                        "deadline_exceeded",
                        attempt,
                        0.0,
                        state.last_class,
                        None,
                        stop_reason=StopReason.DEADLINE_EXCEEDED,
                        cause=state.last_cause,
                    )
                    stop_reason = state.last_stop_reason or StopReason.DEADLINE_EXCEEDED
                    raise RetryExhaustedError(
                        stop_reason=stop_reason,
                        attempts=attempt,
                        last_class=state.last_class,
                        last_exception=None,
                        last_result=state.last_result,
                    )

                if attempt == self.max_attempts:
                    state.last_stop_reason = StopReason.MAX_ATTEMPTS_GLOBAL
                    state.emit(
                        "max_attempts_exceeded",
                        attempt,
                        0.0,
                        state.last_class,
                        None,
                        stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
                        cause=state.last_cause,
                    )
                    stop_reason = state.last_stop_reason or StopReason.MAX_ATTEMPTS_GLOBAL
                    raise RetryExhaustedError(
                        stop_reason=stop_reason,
                        attempts=attempt,
                        last_class=state.last_class,
                        last_exception=None,
                        last_result=state.last_result,
                    )

            except asyncio.CancelledError:
                raise
            except (KeyboardInterrupt, SystemExit):
                raise
            except RetryExhaustedError:
                raise
            except Exception as exc:
                decision = state.handle_exception(exc, attempt)
                if decision.action == "raise":
                    raise

                time.sleep(decision.sleep_s)

                if state.elapsed() > self.deadline:
                    state.last_stop_reason = StopReason.DEADLINE_EXCEEDED
                    state.emit(
                        "deadline_exceeded",
                        attempt,
                        0.0,
                        state.last_class,
                        state.last_exc,
                        stop_reason=StopReason.DEADLINE_EXCEEDED,
                        cause=state.last_cause,
                    )
                    raise

                if attempt == self.max_attempts:
                    state.last_stop_reason = StopReason.MAX_ATTEMPTS_GLOBAL
                    state.emit(
                        "max_attempts_exceeded",
                        attempt,
                        0.0,
                        state.last_class,
                        state.last_exc,
                        stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
                        cause=state.last_cause,
                    )
                    raise

        # Defensive fallback if we exit the loop without returning or raising.
        state.emit(
            "max_attempts_exceeded",
            self.max_attempts,
            0.0,
            state.last_class,
            state.last_exc,
            stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
            cause=state.last_cause,
        )
        state.last_stop_reason = StopReason.MAX_ATTEMPTS_GLOBAL
        if state.last_cause == "result":
            raise RetryExhaustedError(
                stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
                attempts=self.max_attempts,
                last_class=state.last_class,
                last_exception=None,
                last_result=state.last_result,
            )
        if state.last_exc is not None and state.last_exc.__traceback__ is not None:
            raise state.last_exc.with_traceback(state.last_exc.__traceback__)

        # Extremely unlikely: no exception and no result.
        raise RuntimeError("Retry attempts exhausted with no captured exception")

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
    ) -> _RetryContext:
        """
        Context manager that binds hooks/operation for multiple calls.

        Usage:
            with policy.context(on_metric=hook, operation="batch") as retry:
                retry(fn1)
                retry(fn2, arg1, arg2)
        """
        return _RetryContext(self, on_metric, on_log, operation)


class AsyncRetry(_BaseRetryPolicy):
    """
    Async retry loop mirroring Retry semantics for awaitables.
    """

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
    ) -> T:
        """
        Execute an async function with retries according to this policy.

        Result-based failures raise RetryExhaustedError when retries stop.
        """
        state = _RetryState(
            policy=self,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
        )

        for attempt in range(1, self.max_attempts + 1):
            try:
                result = await func()
                if self.result_classifier is None:
                    state.emit("success", attempt, 0.0)
                    return result

                classification_result = self.result_classifier(result)
                if classification_result is None:
                    state.emit("success", attempt, 0.0)
                    return result

                classification = _normalize_classification(classification_result)
                decision = state.handle_result(result, classification, attempt)
                if decision.action == "raise":
                    stop_reason = state.last_stop_reason or StopReason.MAX_ATTEMPTS_GLOBAL
                    raise RetryExhaustedError(
                        stop_reason=stop_reason,
                        attempts=attempt,
                        last_class=state.last_class,
                        last_exception=None,
                        last_result=state.last_result,
                    )

                await asyncio.sleep(decision.sleep_s)

                if state.elapsed() > self.deadline:
                    state.last_stop_reason = StopReason.DEADLINE_EXCEEDED
                    state.emit(
                        "deadline_exceeded",
                        attempt,
                        0.0,
                        state.last_class,
                        None,
                        stop_reason=StopReason.DEADLINE_EXCEEDED,
                        cause=state.last_cause,
                    )
                    stop_reason = state.last_stop_reason or StopReason.DEADLINE_EXCEEDED
                    raise RetryExhaustedError(
                        stop_reason=stop_reason,
                        attempts=attempt,
                        last_class=state.last_class,
                        last_exception=None,
                        last_result=state.last_result,
                    )

                if attempt == self.max_attempts:
                    state.last_stop_reason = StopReason.MAX_ATTEMPTS_GLOBAL
                    state.emit(
                        "max_attempts_exceeded",
                        attempt,
                        0.0,
                        state.last_class,
                        None,
                        stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
                        cause=state.last_cause,
                    )
                    stop_reason = state.last_stop_reason or StopReason.MAX_ATTEMPTS_GLOBAL
                    raise RetryExhaustedError(
                        stop_reason=stop_reason,
                        attempts=attempt,
                        last_class=state.last_class,
                        last_exception=None,
                        last_result=state.last_result,
                    )
            except asyncio.CancelledError:
                raise
            except (KeyboardInterrupt, SystemExit):
                raise
            except RetryExhaustedError:
                raise
            except Exception as exc:
                decision = state.handle_exception(exc, attempt)
                if decision.action == "raise":
                    raise

                await asyncio.sleep(decision.sleep_s)

                if state.elapsed() > self.deadline:
                    state.last_stop_reason = StopReason.DEADLINE_EXCEEDED
                    state.emit(
                        "deadline_exceeded",
                        attempt,
                        0.0,
                        state.last_class,
                        state.last_exc,
                        stop_reason=StopReason.DEADLINE_EXCEEDED,
                        cause=state.last_cause,
                    )
                    raise

                if attempt == self.max_attempts:
                    state.last_stop_reason = StopReason.MAX_ATTEMPTS_GLOBAL
                    state.emit(
                        "max_attempts_exceeded",
                        attempt,
                        0.0,
                        state.last_class,
                        state.last_exc,
                        stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
                        cause=state.last_cause,
                    )
                    raise

        state.emit(
            "max_attempts_exceeded",
            self.max_attempts,
            0.0,
            state.last_class,
            state.last_exc,
            stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
            cause=state.last_cause,
        )
        state.last_stop_reason = StopReason.MAX_ATTEMPTS_GLOBAL
        if state.last_cause == "result":
            raise RetryExhaustedError(
                stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
                attempts=self.max_attempts,
                last_class=state.last_class,
                last_exception=None,
                last_result=state.last_result,
            )

        if state.last_exc is not None and state.last_exc.__traceback__ is not None:
            raise state.last_exc.with_traceback(state.last_exc.__traceback__)

        raise RuntimeError("Retry attempts exhausted with no captured exception")

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
    ) -> _AsyncRetryContext:
        """
        Async context manager that binds hooks/operation for multiple calls.

        Usage:
            async with policy.context(on_metric=hook, operation="batch") as retry:
                await retry(async_fn1)
                await retry(async_fn2, arg)
        """
        return _AsyncRetryContext(self, on_metric, on_log, operation)
