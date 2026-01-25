import asyncio
from collections.abc import Callable
from typing import Any, cast

from ...classify import Classification
from ...errors import AbortRetryError, RetryExhaustedError, StopReason
from ...events import EventName
from ...sleep import SleepFn
from ..base import _BaseRetryPolicy, _normalize_classification
from ..retry_helpers import (
    _abort_outcome,
    _build_outcome,
    _call_attempt_end,
    _call_attempt_end_from_outcome,
    _call_attempt_start,
    _sync_failure_outcome,
)
from ..state import _RetryState
from ..types import (
    AbortPredicate,
    AttemptDecision,
    AttemptHook,
    FailureCause,
    LogHook,
    MetricHook,
    RetryOutcome,
    RetryTimeline,
    T,
)
from .timeline import _resolve_timeline


def _run_sync_call(
    *,
    policy: _BaseRetryPolicy,
    func: Callable[[], Any],
    on_metric: MetricHook | None,
    on_log: LogHook | None,
    operation: str | None,
    abort_if: AbortPredicate | None,
    sleep_fn: SleepFn | None,
    attempt_start_hook: AttemptHook | None,
    attempt_end_hook: AttemptHook | None,
) -> Any:
    state = _RetryState(
        policy=policy,
        on_metric=on_metric,
        on_log=on_log,
        operation=operation,
        abort_if=abort_if,
    )

    for attempt in range(1, policy.max_attempts + 1):
        attempt_started = False
        attempt_end_called = False
        attempt_classification: Classification | None = None
        attempt_result: Any | None = None
        attempt_cause: FailureCause | None = None

        state.check_abort(attempt - 1)
        _call_attempt_start(attempt_start_hook, state=state, attempt=attempt)
        attempt_started = True
        try:
            result = func()
        except AbortRetryError as exc:
            if attempt_started and not attempt_end_called:
                _call_attempt_end(
                    attempt_end_hook,
                    state=state,
                    attempt=attempt,
                    classification=attempt_classification,
                    exception=exc,
                    result=attempt_result,
                    decision=AttemptDecision.ABORTED,
                    stop_reason=StopReason.ABORTED,
                    cause=attempt_cause,
                    sleep_s=None,
                )
                attempt_end_called = True
            if state.last_stop_reason is not StopReason.ABORTED:
                state.last_stop_reason = StopReason.ABORTED
                state.emit(
                    EventName.ABORTED.value,
                    attempt,
                    0.0,
                    stop_reason=StopReason.ABORTED,
                )
            raise
        except asyncio.CancelledError:
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except RetryExhaustedError:
            raise
        except Exception as exc:
            attempt_cause = "exception"
            state.check_abort(attempt)
            decision = state.handle_exception(exc, attempt)
            attempt_classification = state.last_classification
            if decision.action != "raise":
                state.check_abort(attempt)
            outcome = _sync_failure_outcome(
                state=state,
                attempt=attempt,
                decision=decision,
                classification=attempt_classification,
                exception=exc,
                result=None,
                cause=attempt_cause,
                sleep_fn=sleep_fn,
            )
            _call_attempt_end_from_outcome(
                attempt_end_hook,
                state=state,
                attempt=attempt,
                outcome=outcome,
            )
            attempt_end_called = True
            if outcome.decision is AttemptDecision.RETRY:
                continue
            if outcome.decision is AttemptDecision.ABORTED:
                raise AbortRetryError() from None
            if outcome.decision is AttemptDecision.SCHEDULED:
                stop_reason = outcome.stop_reason or state.last_stop_reason or StopReason.SCHEDULED
                raise RetryExhaustedError(
                    stop_reason=stop_reason,
                    attempts=attempt,
                    last_class=state.last_class,
                    last_exception=state.last_exc,
                    last_result=state.last_result,
                    next_sleep_s=outcome.sleep_s,
                ) from None
            raise

        if policy.result_classifier is None:
            state.emit(EventName.SUCCESS.value, attempt, 0.0)
            _call_attempt_end(
                attempt_end_hook,
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
            attempt_end_called = True
            return result

        classification_result = policy.result_classifier(result)
        if classification_result is None:
            state.emit(EventName.SUCCESS.value, attempt, 0.0)
            _call_attempt_end(
                attempt_end_hook,
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
            attempt_end_called = True
            return result

        state.check_abort(attempt)
        classification = _normalize_classification(classification_result)
        attempt_classification = classification
        attempt_result = result
        attempt_cause = "result"
        decision = state.handle_result(result, classification, attempt)
        if decision.action != "raise":
            state.check_abort(attempt)
        outcome = _sync_failure_outcome(
            state=state,
            attempt=attempt,
            decision=decision,
            classification=classification,
            exception=None,
            result=result,
            cause=attempt_cause,
            sleep_fn=sleep_fn,
        )
        _call_attempt_end_from_outcome(
            attempt_end_hook,
            state=state,
            attempt=attempt,
            outcome=outcome,
        )
        attempt_end_called = True
        if outcome.decision is AttemptDecision.RETRY:
            continue
        if outcome.decision is AttemptDecision.ABORTED:
            raise AbortRetryError()

        stop_reason = (
            outcome.stop_reason or state.last_stop_reason or StopReason.MAX_ATTEMPTS_GLOBAL
        )
        next_sleep_s = outcome.sleep_s if outcome.decision is AttemptDecision.SCHEDULED else None
        raise RetryExhaustedError(
            stop_reason=stop_reason,
            attempts=attempt,
            last_class=state.last_class,
            last_exception=None,
            last_result=state.last_result,
            next_sleep_s=next_sleep_s,
        )

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


def _run_sync_execute(
    *,
    policy: _BaseRetryPolicy,
    func: Callable[[], T],
    on_metric: MetricHook | None,
    on_log: LogHook | None,
    operation: str | None,
    abort_if: AbortPredicate | None,
    sleep_fn: SleepFn | None,
    attempt_start_hook: AttemptHook | None,
    attempt_end_hook: AttemptHook | None,
    capture_timeline: bool | RetryTimeline | None,
) -> RetryOutcome[T]:
    timeline, metric_hook = _resolve_timeline(capture_timeline, on_metric)
    state = _RetryState(
        policy=policy,
        on_metric=metric_hook,
        on_log=on_log,
        operation=operation,
        abort_if=abort_if,
    )
    attempts = 0

    for attempt in range(1, policy.max_attempts + 1):
        attempt_started = False
        attempt_end_called = False
        attempt_classification: Classification | None = None
        attempt_result: Any | None = None
        attempt_cause: FailureCause | None = None

        try:
            state.check_abort(attempt - 1)
            _call_attempt_start(attempt_start_hook, state=state, attempt=attempt)
            attempt_started = True
            attempts = attempt
            result = func()
            if policy.result_classifier is None:
                state.emit(EventName.SUCCESS.value, attempt, 0.0)
                _call_attempt_end(
                    attempt_end_hook,
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
                attempt_end_called = True
                return cast(
                    RetryOutcome[T],
                    _build_outcome(
                        ok=True,
                        value=result,
                        state=state,
                        attempts=attempts,
                        timeline=timeline,
                    ),
                )

            classification_result = policy.result_classifier(result)
            if classification_result is None:
                state.emit(EventName.SUCCESS.value, attempt, 0.0)
                _call_attempt_end(
                    attempt_end_hook,
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
                attempt_end_called = True
                return cast(
                    RetryOutcome[T],
                    _build_outcome(
                        ok=True,
                        value=result,
                        state=state,
                        attempts=attempts,
                        timeline=timeline,
                    ),
                )

            state.check_abort(attempt)
            classification = _normalize_classification(classification_result)
            attempt_classification = classification
            attempt_result = result
            attempt_cause = "result"
            decision = state.handle_result(result, classification, attempt)
            if decision.action != "raise":
                state.check_abort(attempt)
            outcome = _sync_failure_outcome(
                state=state,
                attempt=attempt,
                decision=decision,
                classification=classification,
                exception=None,
                result=result,
                cause=attempt_cause,
                sleep_fn=sleep_fn,
            )
            _call_attempt_end_from_outcome(
                attempt_end_hook,
                state=state,
                attempt=attempt,
                outcome=outcome,
            )
            attempt_end_called = True
            if outcome.decision is AttemptDecision.RETRY:
                continue
            if outcome.decision is AttemptDecision.ABORTED:
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
            if attempt_started and not attempt_end_called:
                _call_attempt_end(
                    attempt_end_hook,
                    state=state,
                    attempt=attempt,
                    classification=attempt_classification,
                    exception=exc,
                    result=attempt_result,
                    decision=AttemptDecision.ABORTED,
                    stop_reason=StopReason.ABORTED,
                    cause=attempt_cause,
                    sleep_s=None,
                )
                attempt_end_called = True
            return cast(RetryOutcome[T], _abort_outcome(state, attempts, timeline=timeline))
        except asyncio.CancelledError:
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except RetryExhaustedError:
            raise
        except Exception as exc:
            attempt_cause = "exception"
            try:
                state.check_abort(attempt)
            except AbortRetryError:
                if attempt_started and not attempt_end_called:
                    _call_attempt_end(
                        attempt_end_hook,
                        state=state,
                        attempt=attempt,
                        classification=attempt_classification,
                        exception=exc,
                        result=attempt_result,
                        decision=AttemptDecision.ABORTED,
                        stop_reason=StopReason.ABORTED,
                        cause=attempt_cause,
                        sleep_s=None,
                    )
                    attempt_end_called = True
                return cast(RetryOutcome[T], _abort_outcome(state, attempts, timeline=timeline))

            decision = state.handle_exception(exc, attempt)
            attempt_classification = state.last_classification
            if decision.action != "raise":
                try:
                    state.check_abort(attempt)
                except AbortRetryError:
                    if attempt_started and not attempt_end_called:
                        _call_attempt_end(
                            attempt_end_hook,
                            state=state,
                            attempt=attempt,
                            classification=attempt_classification,
                            exception=exc,
                            result=None,
                            decision=AttemptDecision.ABORTED,
                            stop_reason=StopReason.ABORTED,
                            cause=attempt_cause,
                            sleep_s=None,
                        )
                        attempt_end_called = True
                    return cast(RetryOutcome[T], _abort_outcome(state, attempts, timeline=timeline))

            outcome = _sync_failure_outcome(
                state=state,
                attempt=attempt,
                decision=decision,
                classification=attempt_classification,
                exception=exc,
                result=None,
                cause=attempt_cause,
                sleep_fn=sleep_fn,
            )
            _call_attempt_end_from_outcome(
                attempt_end_hook,
                state=state,
                attempt=attempt,
                outcome=outcome,
            )
            attempt_end_called = True
            if outcome.decision is AttemptDecision.RETRY:
                continue
            if outcome.decision is AttemptDecision.ABORTED:
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
    return cast(
        RetryOutcome[T],
        _build_outcome(ok=False, value=None, state=state, attempts=attempts, timeline=timeline),
    )
