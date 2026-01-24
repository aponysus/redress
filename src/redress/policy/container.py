import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, cast

from ..circuit import CircuitBreaker, CircuitState
from ..classify import default_classifier
from ..errors import (
    AbortRetryError,
    CircuitOpenError,
    ErrorClass,
    RetryExhaustedError,
    StopReason,
)
from .base import _normalize_classification
from .context import _AsyncPolicyContext, _PolicyContext
from .retry import AsyncRetry, Retry
from .types import AbortPredicate, FailureCause, LogHook, MetricHook, RetryOutcome, T


def _emit_breaker_event(
    *,
    event: str,
    state: CircuitState,
    klass: ErrorClass | None,
    on_metric: MetricHook | None,
    on_log: LogHook | None,
    operation: str | None,
) -> None:
    tags: dict[str, Any] = {"state": state.value}
    if klass is not None:
        tags["class"] = klass.name
    if operation:
        tags["operation"] = operation

    if on_metric is not None:
        try:
            on_metric(event, 0, 0.0, tags)
        except Exception:
            pass

    if on_log is not None:
        fields = {"attempt": 0, "sleep_s": 0.0, **tags}
        try:
            on_log(event, fields)
        except Exception:
            pass


def _build_policy_outcome(
    *,
    ok: bool,
    value: Any | None,
    stop_reason: StopReason | None,
    attempts: int,
    last_class: ErrorClass | None,
    last_exception: BaseException | None,
    last_result: Any | None,
    cause: FailureCause | None,
    elapsed_s: float,
) -> RetryOutcome[Any]:
    return RetryOutcome(
        ok=ok,
        value=value if ok else None,
        stop_reason=stop_reason,
        attempts=attempts,
        last_class=last_class,
        last_exception=last_exception,
        last_result=last_result,
        cause=cause,
        elapsed_s=elapsed_s,
    )


class Policy:
    """
    Unified resilience container with an optional retry component.
    """

    def __init__(
        self,
        *,
        retry: Retry | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.retry = retry
        self.circuit_breaker = circuit_breaker

    def call(
        self,
        func: Callable[[], Any],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
    ) -> Any:
        breaker = self.circuit_breaker
        if self.retry is None and abort_if is not None and abort_if():
            if breaker is not None:
                breaker.record_cancel()
            raise AbortRetryError()
        if breaker is not None:
            decision = breaker.allow()
            if decision.event is not None:
                _emit_breaker_event(
                    event=decision.event,
                    state=decision.state,
                    klass=None,
                    on_metric=on_metric,
                    on_log=on_log,
                    operation=operation,
                )
            if not decision.allowed:
                raise CircuitOpenError(decision.state.value)

        try:
            if self.retry is None:
                result = func()
            else:
                result = self.retry.call(
                    func,
                    on_metric=on_metric,
                    on_log=on_log,
                    operation=operation,
                    abort_if=abort_if,
                )
            if breaker is not None:
                event = breaker.record_success()
                if event is not None:
                    _emit_breaker_event(
                        event=event,
                        state=breaker.state,
                        klass=None,
                        on_metric=on_metric,
                        on_log=on_log,
                        operation=operation,
                    )
            return result
        except (KeyboardInterrupt, SystemExit):
            if breaker is not None:
                breaker.record_cancel()
            raise
        except AbortRetryError:
            if breaker is not None:
                breaker.record_cancel()
            raise
        except RetryExhaustedError as exc:
            if breaker is not None:
                klass = exc.last_class or ErrorClass.UNKNOWN
                event = breaker.record_failure(klass)
                if event is not None:
                    _emit_breaker_event(
                        event=event,
                        state=breaker.state,
                        klass=klass,
                        on_metric=on_metric,
                        on_log=on_log,
                        operation=operation,
                    )
            raise
        except Exception as exc:
            if isinstance(exc, CircuitOpenError):
                raise
            if breaker is not None:
                if self.retry is not None:
                    klass = _normalize_classification(self.retry.classifier(exc)).klass
                else:
                    klass = default_classifier(exc)
                event = breaker.record_failure(klass)
                if event is not None:
                    _emit_breaker_event(
                        event=event,
                        state=breaker.state,
                        klass=klass,
                        on_metric=on_metric,
                        on_log=on_log,
                        operation=operation,
                    )
            raise

    def execute(
        self,
        func: Callable[[], Any],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
    ) -> RetryOutcome[Any]:
        start = time.monotonic()
        breaker = self.circuit_breaker
        if self.retry is None and abort_if is not None and abort_if():
            if breaker is not None:
                breaker.record_cancel()
            return _build_policy_outcome(
                ok=False,
                value=None,
                stop_reason=StopReason.ABORTED,
                attempts=0,
                last_class=None,
                last_exception=None,
                last_result=None,
                cause=None,
                elapsed_s=time.monotonic() - start,
            )

        if breaker is not None:
            decision = breaker.allow()
            if decision.event is not None:
                _emit_breaker_event(
                    event=decision.event,
                    state=decision.state,
                    klass=None,
                    on_metric=on_metric,
                    on_log=on_log,
                    operation=operation,
                )
            if not decision.allowed:
                return _build_policy_outcome(
                    ok=False,
                    value=None,
                    stop_reason=None,
                    attempts=0,
                    last_class=None,
                    last_exception=CircuitOpenError(decision.state.value),
                    last_result=None,
                    cause=None,
                    elapsed_s=time.monotonic() - start,
                )

        if self.retry is None:
            try:
                result = func()
            except AbortRetryError:
                if breaker is not None:
                    breaker.record_cancel()
                return _build_policy_outcome(
                    ok=False,
                    value=None,
                    stop_reason=StopReason.ABORTED,
                    attempts=0,
                    last_class=None,
                    last_exception=None,
                    last_result=None,
                    cause=None,
                    elapsed_s=time.monotonic() - start,
                )
            except (KeyboardInterrupt, SystemExit):
                if breaker is not None:
                    breaker.record_cancel()
                raise
            except Exception as exc:
                klass = default_classifier(exc)
                if breaker is not None:
                    event = breaker.record_failure(klass)
                    if event is not None:
                        _emit_breaker_event(
                            event=event,
                            state=breaker.state,
                            klass=klass,
                            on_metric=on_metric,
                            on_log=on_log,
                            operation=operation,
                        )
                return _build_policy_outcome(
                    ok=False,
                    value=None,
                    stop_reason=None,
                    attempts=1,
                    last_class=klass,
                    last_exception=exc,
                    last_result=None,
                    cause="exception",
                    elapsed_s=time.monotonic() - start,
                )

            if breaker is not None:
                event = breaker.record_success()
                if event is not None:
                    _emit_breaker_event(
                        event=event,
                        state=breaker.state,
                        klass=None,
                        on_metric=on_metric,
                        on_log=on_log,
                        operation=operation,
                    )
            return _build_policy_outcome(
                ok=True,
                value=result,
                stop_reason=None,
                attempts=1,
                last_class=None,
                last_exception=None,
                last_result=None,
                cause=None,
                elapsed_s=time.monotonic() - start,
            )

        outcome = self.retry.execute(
            func,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
            abort_if=abort_if,
        )

        if breaker is not None:
            if outcome.ok:
                event = breaker.record_success()
                if event is not None:
                    _emit_breaker_event(
                        event=event,
                        state=breaker.state,
                        klass=None,
                        on_metric=on_metric,
                        on_log=on_log,
                        operation=operation,
                    )
            elif outcome.stop_reason == StopReason.ABORTED:
                breaker.record_cancel()
            else:
                klass = outcome.last_class or ErrorClass.UNKNOWN
                event = breaker.record_failure(klass)
                if event is not None:
                    _emit_breaker_event(
                        event=event,
                        state=breaker.state,
                        klass=klass,
                        on_metric=on_metric,
                        on_log=on_log,
                        operation=operation,
                    )

        return outcome

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
    ) -> _PolicyContext:
        """
        Context manager that binds hooks/operation for multiple calls.
        """
        return _PolicyContext(self, on_metric, on_log, operation, abort_if)


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
    ) -> T:
        breaker = self.circuit_breaker
        if self.retry is None and abort_if is not None and abort_if():
            if breaker is not None:
                breaker.record_cancel()
            raise AbortRetryError()
        if breaker is not None:
            decision = breaker.allow()
            if decision.event is not None:
                _emit_breaker_event(
                    event=decision.event,
                    state=decision.state,
                    klass=None,
                    on_metric=on_metric,
                    on_log=on_log,
                    operation=operation,
                )
            if not decision.allowed:
                raise CircuitOpenError(decision.state.value)

        try:
            if self.retry is None:
                result = await func()
            else:
                result = await self.retry.call(
                    func,
                    on_metric=on_metric,
                    on_log=on_log,
                    operation=operation,
                    abort_if=abort_if,
                )
            if breaker is not None:
                event = breaker.record_success()
                if event is not None:
                    _emit_breaker_event(
                        event=event,
                        state=breaker.state,
                        klass=None,
                        on_metric=on_metric,
                        on_log=on_log,
                        operation=operation,
                    )
            return result
        except asyncio.CancelledError:
            if breaker is not None:
                breaker.record_cancel()
            raise
        except (KeyboardInterrupt, SystemExit):
            if breaker is not None:
                breaker.record_cancel()
            raise
        except AbortRetryError:
            if breaker is not None:
                breaker.record_cancel()
            raise
        except RetryExhaustedError as exc:
            if breaker is not None:
                klass = exc.last_class or ErrorClass.UNKNOWN
                event = breaker.record_failure(klass)
                if event is not None:
                    _emit_breaker_event(
                        event=event,
                        state=breaker.state,
                        klass=klass,
                        on_metric=on_metric,
                        on_log=on_log,
                        operation=operation,
                    )
            raise
        except Exception as exc:
            if isinstance(exc, CircuitOpenError):
                raise
            if breaker is not None:
                if self.retry is not None:
                    klass = _normalize_classification(self.retry.classifier(exc)).klass
                else:
                    klass = default_classifier(exc)
                event = breaker.record_failure(klass)
                if event is not None:
                    _emit_breaker_event(
                        event=event,
                        state=breaker.state,
                        klass=klass,
                        on_metric=on_metric,
                        on_log=on_log,
                        operation=operation,
                    )
            raise

    async def execute(
        self,
        func: Callable[[], Awaitable[T]],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
    ) -> RetryOutcome[T]:
        start = time.monotonic()
        breaker = self.circuit_breaker
        if self.retry is None and abort_if is not None and abort_if():
            if breaker is not None:
                breaker.record_cancel()
            return cast(
                RetryOutcome[T],
                _build_policy_outcome(
                    ok=False,
                    value=None,
                    stop_reason=StopReason.ABORTED,
                    attempts=0,
                    last_class=None,
                    last_exception=None,
                    last_result=None,
                    cause=None,
                    elapsed_s=time.monotonic() - start,
                ),
            )

        if breaker is not None:
            decision = breaker.allow()
            if decision.event is not None:
                _emit_breaker_event(
                    event=decision.event,
                    state=decision.state,
                    klass=None,
                    on_metric=on_metric,
                    on_log=on_log,
                    operation=operation,
                )
            if not decision.allowed:
                return cast(
                    RetryOutcome[T],
                    _build_policy_outcome(
                        ok=False,
                        value=None,
                        stop_reason=None,
                        attempts=0,
                        last_class=None,
                        last_exception=CircuitOpenError(decision.state.value),
                        last_result=None,
                        cause=None,
                        elapsed_s=time.monotonic() - start,
                    ),
                )

        if self.retry is None:
            try:
                result = await func()
            except AbortRetryError:
                if breaker is not None:
                    breaker.record_cancel()
                return cast(
                    RetryOutcome[T],
                    _build_policy_outcome(
                        ok=False,
                        value=None,
                        stop_reason=StopReason.ABORTED,
                        attempts=0,
                        last_class=None,
                        last_exception=None,
                        last_result=None,
                        cause=None,
                        elapsed_s=time.monotonic() - start,
                    ),
                )
            except asyncio.CancelledError:
                if breaker is not None:
                    breaker.record_cancel()
                raise
            except (KeyboardInterrupt, SystemExit):
                if breaker is not None:
                    breaker.record_cancel()
                raise
            except Exception as exc:
                klass = default_classifier(exc)
                if breaker is not None:
                    event = breaker.record_failure(klass)
                    if event is not None:
                        _emit_breaker_event(
                            event=event,
                            state=breaker.state,
                            klass=klass,
                            on_metric=on_metric,
                            on_log=on_log,
                            operation=operation,
                        )
                return cast(
                    RetryOutcome[T],
                    _build_policy_outcome(
                        ok=False,
                        value=None,
                        stop_reason=None,
                        attempts=1,
                        last_class=klass,
                        last_exception=exc,
                        last_result=None,
                        cause="exception",
                        elapsed_s=time.monotonic() - start,
                    ),
                )

            if breaker is not None:
                event = breaker.record_success()
                if event is not None:
                    _emit_breaker_event(
                        event=event,
                        state=breaker.state,
                        klass=None,
                        on_metric=on_metric,
                        on_log=on_log,
                        operation=operation,
                    )
            return cast(
                RetryOutcome[T],
                _build_policy_outcome(
                    ok=True,
                    value=result,
                    stop_reason=None,
                    attempts=1,
                    last_class=None,
                    last_exception=None,
                    last_result=None,
                    cause=None,
                    elapsed_s=time.monotonic() - start,
                ),
            )

        outcome = await self.retry.execute(
            func,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
            abort_if=abort_if,
        )

        if breaker is not None:
            if outcome.ok:
                event = breaker.record_success()
                if event is not None:
                    _emit_breaker_event(
                        event=event,
                        state=breaker.state,
                        klass=None,
                        on_metric=on_metric,
                        on_log=on_log,
                        operation=operation,
                    )
            elif outcome.stop_reason == StopReason.ABORTED:
                breaker.record_cancel()
            else:
                klass = outcome.last_class or ErrorClass.UNKNOWN
                event = breaker.record_failure(klass)
                if event is not None:
                    _emit_breaker_event(
                        event=event,
                        state=breaker.state,
                        klass=klass,
                        on_metric=on_metric,
                        on_log=on_log,
                        operation=operation,
                    )

        return outcome

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
    ) -> _AsyncPolicyContext:
        """
        Async context manager that binds hooks/operation for multiple calls.
        """
        return _AsyncPolicyContext(self, on_metric, on_log, operation, abort_if)
