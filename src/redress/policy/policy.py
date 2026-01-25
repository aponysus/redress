import time
from collections.abc import Callable
from typing import Any

from ..circuit import CircuitBreaker
from ..classify import default_classifier
from ..errors import (
    AbortRetryError,
    CircuitOpenError,
    ErrorClass,
    RetryExhaustedError,
    StopReason,
)
from ..sleep import SleepFn
from .base import _normalize_classification
from .context import _PolicyContext
from .policy_helpers import _build_policy_outcome, _emit_breaker_event
from .retry import Retry
from .types import (
    AbortPredicate,
    AttemptContext,
    AttemptDecision,
    AttemptHook,
    LogHook,
    MetricHook,
    RetryOutcome,
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
        sleep: SleepFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
    ) -> Any:
        breaker = self.circuit_breaker
        start = time.monotonic()
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
                if on_attempt_start is not None:
                    on_attempt_start(
                        AttemptContext(
                            attempt=1,
                            operation=operation,
                            elapsed_s=time.monotonic() - start,
                            classification=None,
                            exception=None,
                            result=None,
                            decision=None,
                            stop_reason=None,
                            cause=None,
                            sleep_s=None,
                        )
                    )
                result = func()
                if on_attempt_end is not None:
                    on_attempt_end(
                        AttemptContext(
                            attempt=1,
                            operation=operation,
                            elapsed_s=time.monotonic() - start,
                            classification=None,
                            exception=None,
                            result=result,
                            decision=AttemptDecision.SUCCESS,
                            stop_reason=None,
                            cause=None,
                            sleep_s=None,
                        )
                    )
            else:
                result = self.retry.call(
                    func,
                    on_metric=on_metric,
                    on_log=on_log,
                    operation=operation,
                    abort_if=abort_if,
                    sleep=sleep,
                    on_attempt_start=on_attempt_start,
                    on_attempt_end=on_attempt_end,
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
        except AbortRetryError as exc:
            if self.retry is None and on_attempt_end is not None:
                on_attempt_end(
                    AttemptContext(
                        attempt=1,
                        operation=operation,
                        elapsed_s=time.monotonic() - start,
                        classification=None,
                        exception=exc,
                        result=None,
                        decision=AttemptDecision.ABORTED,
                        stop_reason=StopReason.ABORTED,
                        cause=None,
                        sleep_s=None,
                    )
                )
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
            if self.retry is None and on_attempt_end is not None:
                on_attempt_end(
                    AttemptContext(
                        attempt=1,
                        operation=operation,
                        elapsed_s=time.monotonic() - start,
                        classification=None,
                        exception=exc,
                        result=None,
                        decision=AttemptDecision.RAISE,
                        stop_reason=None,
                        cause="exception",
                        sleep_s=None,
                    )
                )
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
        sleep: SleepFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
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
                if on_attempt_start is not None:
                    on_attempt_start(
                        AttemptContext(
                            attempt=1,
                            operation=operation,
                            elapsed_s=time.monotonic() - start,
                            classification=None,
                            exception=None,
                            result=None,
                            decision=None,
                            stop_reason=None,
                            cause=None,
                            sleep_s=None,
                        )
                    )
                result = func()
            except AbortRetryError as exc:
                if breaker is not None:
                    breaker.record_cancel()
                if on_attempt_end is not None:
                    on_attempt_end(
                        AttemptContext(
                            attempt=1,
                            operation=operation,
                            elapsed_s=time.monotonic() - start,
                            classification=None,
                            exception=exc,
                            result=None,
                            decision=AttemptDecision.ABORTED,
                            stop_reason=StopReason.ABORTED,
                            cause=None,
                            sleep_s=None,
                        )
                    )
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
                if on_attempt_end is not None:
                    on_attempt_end(
                        AttemptContext(
                            attempt=1,
                            operation=operation,
                            elapsed_s=time.monotonic() - start,
                            classification=None,
                            exception=exc,
                            result=None,
                            decision=AttemptDecision.RAISE,
                            stop_reason=None,
                            cause="exception",
                            sleep_s=None,
                        )
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
            if on_attempt_end is not None:
                on_attempt_end(
                    AttemptContext(
                        attempt=1,
                        operation=operation,
                        elapsed_s=time.monotonic() - start,
                        classification=None,
                        exception=None,
                        result=result,
                        decision=AttemptDecision.SUCCESS,
                        stop_reason=None,
                        cause=None,
                        sleep_s=None,
                    )
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
            sleep=sleep,
            on_attempt_start=on_attempt_start,
            on_attempt_end=on_attempt_end,
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
        sleep: SleepFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
    ) -> _PolicyContext:
        """
        Context manager that binds hooks/operation for multiple calls.
        """
        return _PolicyContext(
            self,
            on_metric,
            on_log,
            operation,
            abort_if,
            sleep,
            on_attempt_start,
            on_attempt_end,
        )
