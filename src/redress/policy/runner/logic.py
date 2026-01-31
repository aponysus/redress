"""
Shared decision logic for sync and async retry runners.

This module contains all non-I/O logic used by both sync_core.py and async_core.py,
eliminating duplication while keeping I/O operations (func invocation, sleep) in
the respective sync/async modules.
"""

from dataclasses import dataclass
from typing import Any, NoReturn

from ...classify import Classification
from ...errors import ErrorClass, RetryExhaustedError, StopReason
from ...events import EventName
from ..base import _BaseRetryPolicy, _normalize_classification
from ..state import _RetryState
from ..types import (
    AttemptDecision,
    FailureCause,
    RetryOutcome,
    RetryTimeline,
)

# ---------------------------------------------------------------------------
# Attempt State Tracking
# ---------------------------------------------------------------------------


@dataclass
class AttemptState:
    """Tracks mutable state within a single attempt iteration."""

    started: bool = False
    end_called: bool = False
    classification: Classification | None = None
    result: Any | None = None
    cause: FailureCause | None = None


# ---------------------------------------------------------------------------
# Action Types (returned by decision functions)
# ---------------------------------------------------------------------------


class LoopAction:
    """Base class for actions returned by decision functions."""

    pass


@dataclass(frozen=True)
class ContinueAction(LoopAction):
    """Continue to the next retry attempt."""

    pass


@dataclass(frozen=True)
class AbortAction(LoopAction):
    """Abort retries and raise AbortRetryError."""

    pass


@dataclass(frozen=True)
class RaiseAction(LoopAction):
    """Re-raise the current exception."""

    pass


@dataclass(frozen=True)
class ScheduledAction(LoopAction):
    """Stop with SCHEDULED status (deferred retry)."""

    stop_reason: StopReason
    attempts: int
    last_class: ErrorClass | None
    last_exception: BaseException | None
    last_result: Any | None
    next_sleep_s: float | None


@dataclass(frozen=True)
class SuccessAction(LoopAction):
    """Return the successful result."""

    result: Any


# ---------------------------------------------------------------------------
# Result Classification
# ---------------------------------------------------------------------------


def should_classify_result(
    policy: _BaseRetryPolicy,
    result: Any,
) -> tuple[bool, Classification | None]:
    """
    Determine if a result should be classified as a failure for retry purposes.

    Returns:
        (should_retry, classification) - If should_retry is False, the result is a success.
    """
    if policy.result_classifier is None:
        return False, None

    classification_result = policy.result_classifier(result)
    if classification_result is None:
        return False, None

    return True, _normalize_classification(classification_result)


# ---------------------------------------------------------------------------
# Decision Functions (from _AttemptOutcome)
# ---------------------------------------------------------------------------


def determine_action_from_outcome(
    outcome: Any,  # _AttemptOutcome from retry_helpers
    state: _RetryState,
    attempt: int,
    *,
    for_result: bool = False,
) -> LoopAction:
    """
    Given an attempt outcome, determine what loop action to take.

    This encapsulates the if/elif chain that appears after _sync_failure_outcome
    and _async_failure_outcome calls in the core runners.

    Args:
        outcome: The _AttemptOutcome from failure processing
        state: Current retry state
        attempt: Current attempt number
        for_result: True if this is for result-based failure (affects RaiseAction behavior)
    """
    if outcome.decision is AttemptDecision.RETRY:
        return ContinueAction()

    if outcome.decision is AttemptDecision.ABORTED:
        return AbortAction()

    if outcome.decision is AttemptDecision.SCHEDULED:
        stop_reason = outcome.stop_reason or state.last_stop_reason or StopReason.SCHEDULED
        return ScheduledAction(
            stop_reason=stop_reason,
            attempts=attempt,
            last_class=state.last_class,
            last_exception=state.last_exc if not for_result else None,
            last_result=state.last_result if for_result else None,
            next_sleep_s=outcome.sleep_s,
        )

    # AttemptDecision.RAISE - but for result-based failures we need to build the error
    if for_result:
        stop_reason = (
            outcome.stop_reason or state.last_stop_reason or StopReason.MAX_ATTEMPTS_GLOBAL
        )
        return ScheduledAction(
            stop_reason=stop_reason,
            attempts=attempt,
            last_class=state.last_class,
            last_exception=None,
            last_result=state.last_result,
            next_sleep_s=outcome.sleep_s if outcome.decision is AttemptDecision.SCHEDULED else None,
        )

    return RaiseAction()


# ---------------------------------------------------------------------------
# Abort Handling
# ---------------------------------------------------------------------------


def handle_abort_in_call(
    state: _RetryState,
    attempt: int,
) -> None:
    """
    Handle AbortRetryError in call mode - emit event if not already emitted.

    This is called after attempt_end has been handled by the caller.
    """
    if state.last_stop_reason is not StopReason.ABORTED:
        state.last_stop_reason = StopReason.ABORTED
        state.emit(
            EventName.ABORTED.value,
            attempt,
            0.0,
            stop_reason=StopReason.ABORTED,
        )


def handle_abort_in_execute(
    state: _RetryState,
    attempts: int,
    timeline: RetryTimeline | None,
) -> RetryOutcome[Any]:
    """
    Handle AbortRetryError in execute mode - emit event and build outcome.
    """
    from ..retry_helpers import _abort_outcome

    return _abort_outcome(state, attempts, timeline=timeline)


# ---------------------------------------------------------------------------
# Success Handling
# ---------------------------------------------------------------------------


def emit_success(state: _RetryState, attempt: int) -> None:
    """Emit success event."""
    state.record_success()
    state.emit(EventName.SUCCESS.value, attempt, 0.0)


def build_success_outcome(
    result: Any,
    state: _RetryState,
    attempts: int,
    timeline: RetryTimeline | None,
) -> RetryOutcome[Any]:
    """Build a successful RetryOutcome."""
    from ..retry_helpers import _build_outcome

    return _build_outcome(
        ok=True,
        value=result,
        state=state,
        attempts=attempts,
        timeline=timeline,
    )


# ---------------------------------------------------------------------------
# Exhaustion Handling
# ---------------------------------------------------------------------------


def emit_max_attempts_exceeded(
    state: _RetryState,
    policy: _BaseRetryPolicy,
) -> None:
    """Emit the max_attempts_exceeded event and update state."""
    state.emit(
        EventName.MAX_ATTEMPTS_EXCEEDED.value,
        policy.max_attempts,
        0.0,
        state.last_class,
        state.last_exc,
        stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
        cause=state.last_cause,
    )
    state.last_stop_reason = StopReason.MAX_ATTEMPTS_GLOBAL


def raise_exhausted_call(state: _RetryState, policy: _BaseRetryPolicy) -> NoReturn:
    """
    Handle retry exhaustion in call mode - emit event and raise appropriate exception.

    This is called when the retry loop completes all attempts without success.
    """
    emit_max_attempts_exceeded(state, policy)

    if state.last_cause == "result":
        raise RetryExhaustedError(
            stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
            attempts=policy.max_attempts,
            last_class=state.last_class,
            last_exception=None,
            last_result=state.last_result,
        )

    if state.last_exc is not None and state.last_exc.__traceback__ is not None:
        raise state.last_exc.with_traceback(state.last_exc.__traceback__)

    raise RuntimeError("Retry attempts exhausted with no captured exception")


def build_exhausted_outcome(
    state: _RetryState,
    policy: _BaseRetryPolicy,
    attempts: int,
    timeline: RetryTimeline | None,
) -> RetryOutcome[Any]:
    """
    Build the outcome when max_attempts is exceeded in execute mode.
    """
    from ..retry_helpers import _build_outcome

    emit_max_attempts_exceeded(state, policy)

    return _build_outcome(
        ok=False,
        value=None,
        state=state,
        attempts=attempts,
        timeline=timeline,
    )


# ---------------------------------------------------------------------------
# Scheduled/Deferred Handling
# ---------------------------------------------------------------------------


def build_scheduled_outcome(
    state: _RetryState,
    attempts: int,
    next_sleep_s: float | None,
    timeline: RetryTimeline | None,
) -> RetryOutcome[Any]:
    """Build outcome for SCHEDULED (deferred) retry."""
    from ..retry_helpers import _build_outcome

    return _build_outcome(
        ok=False,
        value=None,
        state=state,
        attempts=attempts,
        next_sleep_s=next_sleep_s,
        timeline=timeline,
    )


def raise_scheduled(action: ScheduledAction) -> NoReturn:
    """Raise RetryExhaustedError for a scheduled/deferred retry."""
    raise RetryExhaustedError(
        stop_reason=action.stop_reason,
        attempts=action.attempts,
        last_class=action.last_class,
        last_exception=action.last_exception,
        last_result=action.last_result,
        next_sleep_s=action.next_sleep_s,
    ) from None
