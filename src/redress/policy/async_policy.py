"""
Asynchronous Policy class - unified resilience container.

Uses shared helpers from execution.py for circuit breaker integration.
"""

import asyncio
from collections.abc import Awaitable, Callable

from ..circuit import CircuitBreaker
from ..errors import (
    AbortRetryError,
    CircuitOpenError,
    ErrorClass,
    RetryExhaustedError,
    StopReason,
)
from ..sleep import (
    AsyncBeforeSleepHook,
    AsyncSleeperFn,
    BeforeSleepHook,
    SleeperFn,
    SleepFn,
)
from .context import _AsyncPolicyContext
from .execution import (
    ExecutionContext,
    build_aborted_outcome,
    build_circuit_open_outcome,
    build_exception_outcome_no_retry,
    build_success_outcome_no_retry,
    check_abort_no_retry,
    check_breaker,
    classify_for_breaker,
    make_attempt_context,
    record_cancel,
    record_failure,
    record_success,
)
from .retry import AsyncRetry
from .types import (
    AbortPredicate,
    AttemptDecision,
    AttemptHook,
    LogHook,
    MetricHook,
    RetryOutcome,
    RetryTimeline,
    T,
)


class AsyncPolicy:
    """
    Unified resilience container with an optional async retry component.
    """

    def __init__(
        self,
        *,
        retry: AsyncRetry | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.retry = retry
        self.circuit_breaker = circuit_breaker

    async def call(
        self,
        func: Callable[[], Awaitable[T]],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
        sleep: SleepFn | None = None,
        before_sleep: BeforeSleepHook | AsyncBeforeSleepHook | None = None,
        sleeper: SleeperFn | AsyncSleeperFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
    ) -> T:
        ctx = ExecutionContext.create(self.circuit_breaker, on_metric, on_log, operation)

        # Pre-flight abort check (no retry configured)
        if self.retry is None and check_abort_no_retry(ctx, abort_if):
            raise AbortRetryError()

        # Circuit breaker check
        check_breaker(ctx)

        try:
            if self.retry is None:
                result = await self._call_without_retry(ctx, func, on_attempt_start, on_attempt_end)
            else:
                result = await self.retry.call(
                    func,
                    on_metric=on_metric,
                    on_log=on_log,
                    operation=operation,
                    abort_if=abort_if,
                    sleep=sleep,
                    before_sleep=before_sleep,
                    sleeper=sleeper,
                    on_attempt_start=on_attempt_start,
                    on_attempt_end=on_attempt_end,
                )
            record_success(ctx)
            return result

        except asyncio.CancelledError:
            record_cancel(ctx)
            raise
        except (KeyboardInterrupt, SystemExit):
            record_cancel(ctx)
            raise
        except AbortRetryError as exc:
            self._handle_abort_call(ctx, exc, on_attempt_end)
            raise
        except RetryExhaustedError as exc:
            self._handle_exhausted_call(ctx, exc)
            raise
        except Exception as exc:
            self._handle_exception_call(ctx, exc, on_attempt_end)
            raise

    async def _call_without_retry(
        self,
        ctx: ExecutionContext,
        func: Callable[[], Awaitable[T]],
        on_start: AttemptHook | None,
        on_end: AttemptHook | None,
    ) -> T:
        """Execute async func without retry wrapper."""
        if on_start is not None:
            on_start(make_attempt_context(1, ctx.operation, ctx.elapsed()))

        result = await func()

        if on_end is not None:
            on_end(
                make_attempt_context(
                    1,
                    ctx.operation,
                    ctx.elapsed(),
                    result=result,
                    decision=AttemptDecision.SUCCESS,
                )
            )

        return result

    def _handle_abort_call(
        self,
        ctx: ExecutionContext,
        exc: AbortRetryError,
        on_end: AttemptHook | None,
    ) -> None:
        """Handle AbortRetryError in call mode."""
        if self.retry is None and on_end is not None:
            on_end(
                make_attempt_context(
                    1,
                    ctx.operation,
                    ctx.elapsed(),
                    exception=exc,
                    decision=AttemptDecision.ABORTED,
                    stop_reason=StopReason.ABORTED,
                )
            )
        record_cancel(ctx)

    def _handle_exhausted_call(
        self,
        ctx: ExecutionContext,
        exc: RetryExhaustedError,
    ) -> None:
        """Handle RetryExhaustedError in call mode."""
        klass = exc.last_class or ErrorClass.UNKNOWN
        record_failure(ctx, klass)

    def _handle_exception_call(
        self,
        ctx: ExecutionContext,
        exc: Exception,
        on_end: AttemptHook | None,
    ) -> None:
        """Handle general exception in call mode."""
        if isinstance(exc, CircuitOpenError):
            return

        if self.retry is None and on_end is not None:
            on_end(
                make_attempt_context(
                    1,
                    ctx.operation,
                    ctx.elapsed(),
                    exception=exc,
                    decision=AttemptDecision.RAISE,
                    cause="exception",
                )
            )

        klass = classify_for_breaker(exc, self.retry)
        record_failure(ctx, klass)

    async def execute(
        self,
        func: Callable[[], Awaitable[T]],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
        sleep: SleepFn | None = None,
        before_sleep: BeforeSleepHook | AsyncBeforeSleepHook | None = None,
        sleeper: SleeperFn | AsyncSleeperFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
        capture_timeline: bool | RetryTimeline | None = None,
    ) -> RetryOutcome[T]:
        ctx = ExecutionContext.create(self.circuit_breaker, on_metric, on_log, operation)

        # Pre-flight abort check (no retry configured)
        if self.retry is None and check_abort_no_retry(ctx, abort_if):
            return build_aborted_outcome(ctx)

        # Circuit breaker check
        if ctx.breaker is not None:
            decision = ctx.breaker.allow()
            ctx.emit_breaker_event(decision.event, decision.state)
            if not decision.allowed:
                return build_circuit_open_outcome(ctx, decision.state.value)

        # Delegate to retry if configured
        if self.retry is not None:
            return await self._execute_with_retry(
                ctx,
                func,
                on_metric,
                on_log,
                operation,
                abort_if,
                sleep,
                before_sleep,
                sleeper,
                on_attempt_start,
                on_attempt_end,
                capture_timeline,
            )

        # No retry - single attempt
        return await self._execute_without_retry(ctx, func, on_attempt_start, on_attempt_end)

    async def _execute_with_retry(
        self,
        ctx: ExecutionContext,
        func: Callable[[], Awaitable[T]],
        on_metric: MetricHook | None,
        on_log: LogHook | None,
        operation: str | None,
        abort_if: AbortPredicate | None,
        sleep: SleepFn | None,
        before_sleep: BeforeSleepHook | AsyncBeforeSleepHook | None,
        sleeper: SleeperFn | AsyncSleeperFn | None,
        on_attempt_start: AttemptHook | None,
        on_attempt_end: AttemptHook | None,
        capture_timeline: bool | RetryTimeline | None,
    ) -> RetryOutcome[T]:
        """Execute with retry and record result with breaker."""
        retry = self.retry
        assert retry is not None
        outcome = await retry.execute(
            func,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
            abort_if=abort_if,
            sleep=sleep,
            before_sleep=before_sleep,
            sleeper=sleeper,
            on_attempt_start=on_attempt_start,
            on_attempt_end=on_attempt_end,
            capture_timeline=capture_timeline,
        )

        # Record with circuit breaker
        if ctx.breaker is not None:
            if outcome.ok:
                record_success(ctx)
            elif outcome.stop_reason == StopReason.ABORTED:
                record_cancel(ctx)
            else:
                klass = outcome.last_class or ErrorClass.UNKNOWN
                record_failure(ctx, klass)

        return outcome

    async def _execute_without_retry(
        self,
        ctx: ExecutionContext,
        func: Callable[[], Awaitable[T]],
        on_start: AttemptHook | None,
        on_end: AttemptHook | None,
    ) -> RetryOutcome[T]:
        """Execute single async attempt without retry."""
        try:
            if on_start is not None:
                on_start(make_attempt_context(1, ctx.operation, ctx.elapsed()))

            result = await func()

        except AbortRetryError as exc:
            record_cancel(ctx)
            if on_end is not None:
                on_end(
                    make_attempt_context(
                        1,
                        ctx.operation,
                        ctx.elapsed(),
                        exception=exc,
                        decision=AttemptDecision.ABORTED,
                        stop_reason=StopReason.ABORTED,
                    )
                )
            return build_aborted_outcome(ctx)

        except asyncio.CancelledError:
            record_cancel(ctx)
            raise

        except (KeyboardInterrupt, SystemExit):
            record_cancel(ctx)
            raise

        except Exception as exc:
            klass = classify_for_breaker(exc, None)
            record_failure(ctx, klass)
            if on_end is not None:
                on_end(
                    make_attempt_context(
                        1,
                        ctx.operation,
                        ctx.elapsed(),
                        exception=exc,
                        decision=AttemptDecision.RAISE,
                        cause="exception",
                    )
                )
            return build_exception_outcome_no_retry(ctx, exc, klass)

        # Success
        record_success(ctx)
        if on_end is not None:
            on_end(
                make_attempt_context(
                    1,
                    ctx.operation,
                    ctx.elapsed(),
                    result=result,
                    decision=AttemptDecision.SUCCESS,
                )
            )
        return build_success_outcome_no_retry(ctx, result)

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
        sleep: SleepFn | None = None,
        before_sleep: BeforeSleepHook | AsyncBeforeSleepHook | None = None,
        sleeper: SleeperFn | AsyncSleeperFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
    ) -> _AsyncPolicyContext:
        """
        Async context manager that binds hooks/operation for multiple calls.
        """
        return _AsyncPolicyContext(
            self,
            on_metric,
            on_log,
            operation,
            abort_if,
            sleep,
            before_sleep,
            sleeper,
            on_attempt_start,
            on_attempt_end,
        )
