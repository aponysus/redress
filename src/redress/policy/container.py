import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from ..circuit import CircuitBreaker, CircuitState
from ..classify import default_classifier
from ..errors import CircuitOpenError, ErrorClass, RetryExhaustedError
from .base import _normalize_classification
from .context import _AsyncPolicyContext, _PolicyContext
from .retry import AsyncRetry, Retry
from .types import LogHook, MetricHook, T


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
    ) -> Any:
        breaker = self.circuit_breaker
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

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
    ) -> _PolicyContext:
        """
        Context manager that binds hooks/operation for multiple calls.
        """
        return _PolicyContext(self, on_metric, on_log, operation)


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
    ) -> T:
        breaker = self.circuit_breaker
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

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
    ) -> _AsyncPolicyContext:
        """
        Async context manager that binds hooks/operation for multiple calls.
        """
        return _AsyncPolicyContext(self, on_metric, on_log, operation)
