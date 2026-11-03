"""
Execution context and helpers for Policy classes.

This module provides shared infrastructure for both sync and async Policy classes,
reducing duplication in policy.py and async_policy.py.
"""

import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal

from ..circuit import CircuitBreaker, CircuitState, _BreakerDecision
from ..classify import default_classifier
from ..errors import (
    CircuitOpenError,
    ErrorClass,
    StopReason,
)
from .base import _normalize_classification
from .policy_helpers import _build_policy_outcome, _emit_breaker_event
from .types import (
    AbortPredicate,
    AttemptContext,
    AttemptDecision,
    FailureCause,
    LogHook,
    MetricHook,
    RetryOutcome,
)

# ---------------------------------------------------------------------------
# Execution Context
# ---------------------------------------------------------------------------


@dataclass
class ExecutionContext:
    """
    Shared context for a single policy execution (call or execute).

    Holds references to the circuit breaker, hooks, and timing information
    that are used throughout the execution lifecycle.
    """

    start: float
    breaker: CircuitBreaker | None
    on_metric: MetricHook | None
    on_log: LogHook | None
    operation: str | None
    breaker_decision: _BreakerDecision | None = None

    def __enter__(self) -> "ExecutionContext":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # This also covers failures in admission events and exception handlers.
        record_cancel(self)

    @classmethod
    def create(
        cls,
        breaker: CircuitBreaker | None,
        on_metric: MetricHook | None,
        on_log: LogHook | None,
        operation: str | None,
    ) -> "ExecutionContext":
        """Factory method to create a new execution context."""
        return cls(
            start=time.monotonic(),
            breaker=breaker,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
        )

    def elapsed(self) -> float:
        """Return elapsed time since execution started."""
        return time.monotonic() - self.start

    def emit_breaker_event(
        self,
        event: str | None,
        state: CircuitState,
        klass: ErrorClass | None = None,
    ) -> None:
        """Emit a circuit breaker event if event is not None."""
        if event is not None:
            _emit_breaker_event(
                event=event,
                state=state,
                klass=klass,
                on_metric=self.on_metric,
                on_log=self.on_log,
                operation=self.operation,
            )


# ---------------------------------------------------------------------------
# Circuit Breaker Helpers
# ---------------------------------------------------------------------------


def check_breaker(ctx: ExecutionContext) -> None:
    """
    Check circuit breaker and raise CircuitOpenError if open.

    Emits breaker events as appropriate.
    """
    if ctx.breaker is None:
        return

    decision = ctx.breaker.allow()
    ctx.breaker_decision = decision if decision.allowed else None
    ctx.emit_breaker_event(decision.event, decision.state)

    if not decision.allowed:
        raise CircuitOpenError(decision.state.value)


def record_success(ctx: ExecutionContext) -> None:
    """Record success with circuit breaker and emit event if state changed."""
    _complete_breaker(ctx, "success")


def record_cancel(ctx: ExecutionContext) -> None:
    """Record cancellation with circuit breaker (no event emitted)."""
    _complete_breaker(ctx, "cancel")


def record_failure(ctx: ExecutionContext, klass: ErrorClass) -> None:
    """Record failure with circuit breaker and emit event if state changed."""
    _complete_breaker(ctx, "failure", klass)


def _complete_breaker(
    ctx: ExecutionContext,
    outcome: Literal["success", "failure", "cancel"],
    klass: ErrorClass | None = None,
) -> None:
    breaker = ctx.breaker
    decision = ctx.breaker_decision
    if breaker is None or decision is None:
        return

    if isinstance(breaker, CircuitBreaker):
        event = breaker._complete(decision, outcome, klass)
    elif outcome == "success":
        # Preserve support for duck-typed breakers such as FakeCircuitBreaker.
        event = breaker.record_success()
    elif outcome == "failure":
        assert klass is not None
        event = breaker.record_failure(klass)
    else:
        breaker.record_cancel()
        event = None

    # Retire the context before observers run: an observer may start another probe.
    ctx.breaker_decision = None
    ctx.emit_breaker_event(event, breaker.state, klass)


def classify_for_breaker(exc: BaseException, retry: Any) -> ErrorClass:
    """
    Classify an exception for circuit breaker recording.

    Uses the retry's classifier if available, otherwise falls back to default_classifier.
    """
    if retry is not None:
        return _normalize_classification(retry.classifier(exc)).klass
    return default_classifier(exc)


# ---------------------------------------------------------------------------
# Abort Checking
# ---------------------------------------------------------------------------


def check_abort_no_retry(
    ctx: ExecutionContext,
    abort_if: AbortPredicate | None,
) -> bool:
    """
    Check abort predicate when there's no retry policy configured.

    Returns True if execution should abort before acquiring breaker admission.
    """
    if abort_if is not None and abort_if():
        return True
    return False


# ---------------------------------------------------------------------------
# Attempt Context Factory
# ---------------------------------------------------------------------------


def make_attempt_context(
    attempt: int,
    operation: str | None,
    elapsed_s: float,
    *,
    classification: Any = None,
    exception: BaseException | None = None,
    result: Any = None,
    decision: AttemptDecision | None = None,
    stop_reason: StopReason | None = None,
    cause: FailureCause | None = None,
    sleep_s: float | None = None,
) -> AttemptContext:
    """
    Factory for AttemptContext with sensible defaults.

    This reduces boilerplate when creating AttemptContext instances
    throughout the Policy classes.
    """
    return AttemptContext(
        attempt=attempt,
        operation=operation,
        elapsed_s=elapsed_s,
        classification=classification,
        exception=exception,
        result=result,
        decision=decision,
        stop_reason=stop_reason,
        cause=cause,
        sleep_s=sleep_s,
    )


# ---------------------------------------------------------------------------
# Outcome Builders for Policy (no-retry case)
# ---------------------------------------------------------------------------


def build_aborted_outcome(ctx: ExecutionContext) -> RetryOutcome[Any]:
    """Build outcome for aborted execution (no retry configured)."""
    return _build_policy_outcome(
        ok=False,
        value=None,
        stop_reason=StopReason.ABORTED,
        attempts=0,
        last_class=None,
        last_exception=None,
        last_result=None,
        cause=None,
        elapsed_s=ctx.elapsed(),
    )


def build_circuit_open_outcome(
    ctx: ExecutionContext,
    state_value: str,
) -> RetryOutcome[Any]:
    """Build outcome when circuit breaker rejects the call."""
    return _build_policy_outcome(
        ok=False,
        value=None,
        stop_reason=None,
        attempts=0,
        last_class=None,
        last_exception=CircuitOpenError(state_value),
        last_result=None,
        cause=None,
        elapsed_s=ctx.elapsed(),
    )


def build_success_outcome_no_retry(
    ctx: ExecutionContext,
    result: Any,
) -> RetryOutcome[Any]:
    """Build success outcome when no retry is configured."""
    return _build_policy_outcome(
        ok=True,
        value=result,
        stop_reason=None,
        attempts=1,
        last_class=None,
        last_exception=None,
        last_result=None,
        cause=None,
        elapsed_s=ctx.elapsed(),
    )


def build_exception_outcome_no_retry(
    ctx: ExecutionContext,
    exc: BaseException,
    klass: ErrorClass,
) -> RetryOutcome[Any]:
    """Build outcome for exception when no retry is configured."""
    return _build_policy_outcome(
        ok=False,
        value=None,
        stop_reason=None,
        attempts=1,
        last_class=klass,
        last_exception=exc,
        last_result=None,
        cause="exception",
        elapsed_s=ctx.elapsed(),
    )
