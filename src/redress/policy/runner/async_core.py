"""
Asynchronous retry runner.

This module implements the async retry loop. It uses shared logic from
logic.py for decision-making while keeping I/O operations (func calls, sleep) here.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast

from ...errors import AbortRetryError, RetryExhaustedError, StopReason
from ...sleep import (
    AsyncBeforeSleepHook,
    AsyncSleeperFn,
    BeforeSleepHook,
    SleeperFn,
    SleepFn,
)
from ..base import _BaseRetryPolicy
from ..retry_helpers import (
    _abort_outcome,
    _async_failure_outcome,
    _build_outcome,
    _call_attempt_end,
    _call_attempt_end_from_outcome,
    _call_attempt_start,
)
from ..state import _RetryState
from ..types import (
    AbortPredicate,
    AttemptDecision,
    AttemptHook,
    LogHook,
    MetricHook,
    RetryOutcome,
    RetryTimeline,
    T,
)
from .logic import (
    AbortAction,
    AttemptState,
    ContinueAction,
    ScheduledAction,
    build_exhausted_outcome,
    determine_action_from_outcome,
    emit_success,
    handle_abort_in_call,
    raise_exhausted_call,
    raise_scheduled,
    should_classify_result,
)
from .timeline import _resolve_timeline


def _handle_abort_attempt_end(
    hook: AttemptHook | None,
    state: _RetryState,
    attempt: int,
    attempt_state: AttemptState,
    exc: BaseException,
) -> None:
    """Call attempt_end hook for abort if not already called."""
    if attempt_state.started and not attempt_state.end_called:
        _call_attempt_end(
            hook,
            state=state,
            attempt=attempt,
            classification=attempt_state.classification,
            exception=exc,
            result=attempt_state.result,
            decision=AttemptDecision.ABORTED,
            stop_reason=StopReason.ABORTED,
            cause=attempt_state.cause,
            sleep_s=None,
        )
        attempt_state.end_called = True


def _handle_success_attempt_end(
    hook: AttemptHook | None,
    state: _RetryState,
    attempt: int,
    result: Any,
) -> None:
    """Emit success and call attempt_end hook."""
    emit_success(state, attempt)
    _call_attempt_end(
        hook,
        state=state,
        attempt=attempt,
        classification=None,
        exception=None,
        result=result,
        decision=AttemptDecision.SUCCESS,
        stop_reason=None,
        cause=None,
        sleep_s=None,
    )


async def _run_async_call(
    *,
    policy: _BaseRetryPolicy,
    func: Callable[[], Awaitable[T]],
    on_metric: MetricHook | None,
    on_log: LogHook | None,
    operation: str | None,
    abort_if: AbortPredicate | None,
    sleep_fn: SleepFn | None,
    before_sleep: BeforeSleepHook | AsyncBeforeSleepHook | None,
    sleeper: SleeperFn | AsyncSleeperFn | None,
    attempt_start_hook: AttemptHook | None,
    attempt_end_hook: AttemptHook | None,
) -> T:
    """Execute async func with retries, raising on failure."""
    state = _RetryState(
        policy=policy,
        on_metric=on_metric,
        on_log=on_log,
        operation=operation,
        abort_if=abort_if,
    )
    attempt_timeout_s = policy.attempt_timeout_s

    for attempt in range(1, policy.max_attempts + 1):
        attempt_state = AttemptState()

        state.check_abort(attempt - 1)
        _call_attempt_start(attempt_start_hook, state=state, attempt=attempt)
        attempt_state.started = True

        try:
            if attempt_timeout_s is None:
                result = await func()
            else:
                result = await asyncio.wait_for(func(), timeout=attempt_timeout_s)
        except AbortRetryError as exc:
            _handle_abort_attempt_end(attempt_end_hook, state, attempt, attempt_state, exc)
            handle_abort_in_call(state, attempt)
            raise
        except asyncio.CancelledError:
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except RetryExhaustedError:
            raise
        except Exception as exc:
            attempt_state.cause = "exception"
            state.check_abort(attempt)
            decision = state.handle_exception(exc, attempt)
            attempt_state.classification = state.last_classification
            if decision.action != "raise":
                state.check_abort(attempt)

            outcome = await _async_failure_outcome(
                state=state,
                attempt=attempt,
                decision=decision,
                classification=attempt_state.classification,
                exception=exc,
                result=None,
                cause=attempt_state.cause,
                sleep_fn=sleep_fn,
                before_sleep=before_sleep,
                sleeper=sleeper,
            )
            _call_attempt_end_from_outcome(
                attempt_end_hook, state=state, attempt=attempt, outcome=outcome
            )
            attempt_state.end_called = True

            action = determine_action_from_outcome(outcome, state, attempt)
            if isinstance(action, ContinueAction):
                continue
            if isinstance(action, AbortAction):
                raise AbortRetryError() from None
            if isinstance(action, ScheduledAction):
                raise_scheduled(action)
            raise

        # Success path: check if result needs classification
        needs_retry, classification = should_classify_result(policy, result)
        if not needs_retry:
            _handle_success_attempt_end(attempt_end_hook, state, attempt, result)
            return result
        assert classification is not None

        # Result-based retry
        state.check_abort(attempt)
        attempt_state.classification = classification
        attempt_state.result = result
        attempt_state.cause = "result"
        decision = state.handle_result(result, classification, attempt)
        if decision.action != "raise":
            state.check_abort(attempt)

        outcome = await _async_failure_outcome(
            state=state,
            attempt=attempt,
            decision=decision,
            classification=classification,
            exception=None,
            result=result,
            cause=attempt_state.cause,
            sleep_fn=sleep_fn,
            before_sleep=before_sleep,
            sleeper=sleeper,
        )
        _call_attempt_end_from_outcome(
            attempt_end_hook, state=state, attempt=attempt, outcome=outcome
        )
        attempt_state.end_called = True

        action = determine_action_from_outcome(outcome, state, attempt, for_result=True)
        if isinstance(action, ContinueAction):
            continue
        if isinstance(action, AbortAction):
            raise AbortRetryError()
        if isinstance(action, ScheduledAction):
            raise_scheduled(action)
        raise RetryExhaustedError(
            stop_reason=(
                action.stop_reason
                if isinstance(action, ScheduledAction)
                else state.last_stop_reason or StopReason.MAX_ATTEMPTS_GLOBAL
            ),
            attempts=attempt,
            last_class=state.last_class,
            last_exception=None,
            last_result=state.last_result,
        )

    raise_exhausted_call(state, policy)


async def _run_async_execute(
    *,
    policy: _BaseRetryPolicy,
    func: Callable[[], Awaitable[T]],
    on_metric: MetricHook | None,
    on_log: LogHook | None,
    operation: str | None,
    abort_if: AbortPredicate | None,
    sleep_fn: SleepFn | None,
    before_sleep: BeforeSleepHook | AsyncBeforeSleepHook | None,
    sleeper: SleeperFn | AsyncSleeperFn | None,
    attempt_start_hook: AttemptHook | None,
    attempt_end_hook: AttemptHook | None,
    capture_timeline: bool | RetryTimeline | None,
) -> RetryOutcome[T]:
    """Execute async func with retries, returning outcome."""
    timeline, metric_hook = _resolve_timeline(capture_timeline, on_metric)
    state = _RetryState(
        policy=policy,
        on_metric=metric_hook,
        on_log=on_log,
        operation=operation,
        abort_if=abort_if,
    )
    attempts = 0
    attempt_timeout_s = policy.attempt_timeout_s

    for attempt in range(1, policy.max_attempts + 1):
        attempt_state = AttemptState()

        try:
            state.check_abort(attempt - 1)
            _call_attempt_start(attempt_start_hook, state=state, attempt=attempt)
            attempt_state.started = True
            attempts = attempt

            if attempt_timeout_s is None:
                result = await func()
            else:
                result = await asyncio.wait_for(func(), timeout=attempt_timeout_s)

            # Success path: check if result needs classification
            needs_retry, classification = should_classify_result(policy, result)
            if not needs_retry:
                _handle_success_attempt_end(attempt_end_hook, state, attempt, result)
                return cast(
                    RetryOutcome[T],
                    _build_outcome(
                        ok=True, value=result, state=state, attempts=attempts, timeline=timeline
                    ),
                )
            assert classification is not None

            # Result-based retry
            state.check_abort(attempt)
            attempt_state.classification = classification
            attempt_state.result = result
            attempt_state.cause = "result"
            decision = state.handle_result(result, classification, attempt)
            if decision.action != "raise":
                state.check_abort(attempt)

            outcome = await _async_failure_outcome(
                state=state,
                attempt=attempt,
                decision=decision,
                classification=classification,
                exception=None,
                result=result,
                cause=attempt_state.cause,
                sleep_fn=sleep_fn,
                before_sleep=before_sleep,
                sleeper=sleeper,
            )
            _call_attempt_end_from_outcome(
                attempt_end_hook, state=state, attempt=attempt, outcome=outcome
            )
            attempt_state.end_called = True

            action = determine_action_from_outcome(outcome, state, attempt, for_result=True)
            if isinstance(action, ContinueAction):
                continue
            if isinstance(action, AbortAction):
                return cast(RetryOutcome[T], _abort_outcome(state, attempts, timeline=timeline))

            next_sleep_s = (
                outcome.sleep_s if outcome.decision is AttemptDecision.SCHEDULED else None
            )
            return cast(
                RetryOutcome[T],
                _build_outcome(
                    ok=False,
                    value=None,
                    state=state,
                    attempts=attempts,
                    next_sleep_s=next_sleep_s,
                    timeline=timeline,
                ),
            )

        except AbortRetryError as exc:
            _handle_abort_attempt_end(attempt_end_hook, state, attempt, attempt_state, exc)
            return cast(RetryOutcome[T], _abort_outcome(state, attempts, timeline=timeline))
        except asyncio.CancelledError:
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except RetryExhaustedError:
            raise
        except Exception as exc:
            attempt_state.cause = "exception"
            try:
                state.check_abort(attempt)
            except AbortRetryError:
                _handle_abort_attempt_end(attempt_end_hook, state, attempt, attempt_state, exc)
                return cast(RetryOutcome[T], _abort_outcome(state, attempts, timeline=timeline))

            decision = state.handle_exception(exc, attempt)
            attempt_state.classification = state.last_classification
            if decision.action != "raise":
                try:
                    state.check_abort(attempt)
                except AbortRetryError:
                    _handle_abort_attempt_end(attempt_end_hook, state, attempt, attempt_state, exc)
                    return cast(RetryOutcome[T], _abort_outcome(state, attempts, timeline=timeline))

            outcome = await _async_failure_outcome(
                state=state,
                attempt=attempt,
                decision=decision,
                classification=attempt_state.classification,
                exception=exc,
                result=None,
                cause=attempt_state.cause,
                sleep_fn=sleep_fn,
                before_sleep=before_sleep,
                sleeper=sleeper,
            )
            _call_attempt_end_from_outcome(
                attempt_end_hook, state=state, attempt=attempt, outcome=outcome
            )
            attempt_state.end_called = True

            action = determine_action_from_outcome(outcome, state, attempt)
            if isinstance(action, ContinueAction):
                continue
            if isinstance(action, AbortAction):
                return cast(RetryOutcome[T], _abort_outcome(state, attempts, timeline=timeline))

            next_sleep_s = (
                outcome.sleep_s if outcome.decision is AttemptDecision.SCHEDULED else None
            )
            return cast(
                RetryOutcome[T],
                _build_outcome(
                    ok=False,
                    value=None,
                    state=state,
                    attempts=attempts,
                    next_sleep_s=next_sleep_s,
                    timeline=timeline,
                ),
            )

    return cast(RetryOutcome[T], build_exhausted_outcome(state, policy, attempts, timeline))
