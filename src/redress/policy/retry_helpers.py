import asyncio
import time
from dataclasses import dataclass
from typing import Any

from ..classify import Classification
from ..errors import StopReason
from ..events import EventName
from ..sleep import SleepDecision, SleepFn
from .state import _RetryDecision, _RetryState
from .types import AttemptContext, AttemptDecision, AttemptHook, FailureCause, RetryOutcome


@dataclass(frozen=True)
class _AttemptOutcome:
    decision: AttemptDecision
    classification: Classification | None
    exception: BaseException | None
    result: Any | None
    cause: FailureCause | None
    stop_reason: StopReason | None
    sleep_s: float | None


def _build_outcome(
    *,
    ok: bool,
    value: Any | None,
    state: _RetryState,
    attempts: int,
    next_sleep_s: float | None = None,
) -> RetryOutcome[Any]:
    last_exception: BaseException | None = None
    last_result: Any | None = None
    if not ok and state.last_cause == "exception":
        last_exception = state.last_exc
    if not ok and state.last_cause == "result":
        last_result = state.last_result

    return RetryOutcome(
        ok=ok,
        value=value if ok else None,
        stop_reason=None if ok else state.last_stop_reason,
        attempts=attempts,
        last_class=None if ok else state.last_class,
        last_exception=last_exception,
        last_result=last_result,
        cause=None if ok else state.last_cause,
        elapsed_s=state.elapsed().total_seconds(),
        next_sleep_s=next_sleep_s,
    )


def _abort_outcome(state: _RetryState, attempts: int) -> RetryOutcome[Any]:
    if state.last_stop_reason is not StopReason.ABORTED:
        state.last_stop_reason = StopReason.ABORTED
        state.emit(
            EventName.ABORTED.value,
            attempts,
            0.0,
            stop_reason=StopReason.ABORTED,
        )
    return _build_outcome(ok=False, value=None, state=state, attempts=attempts)


def _resolve_sleep(policy_sleep: SleepFn | None, call_sleep: SleepFn | None) -> SleepFn | None:
    return call_sleep if call_sleep is not None else policy_sleep


def _resolve_attempt_hooks(
    *,
    policy_start: AttemptHook | None,
    policy_end: AttemptHook | None,
    call_start: AttemptHook | None,
    call_end: AttemptHook | None,
) -> tuple[AttemptHook | None, AttemptHook | None]:
    start = call_start if call_start is not None else policy_start
    end = call_end if call_end is not None else policy_end
    return start, end


def _call_attempt_start(
    hook: AttemptHook | None,
    *,
    state: _RetryState,
    attempt: int,
) -> None:
    if hook is None:
        return
    ctx = AttemptContext(
        attempt=attempt,
        operation=state.operation,
        elapsed_s=state.elapsed().total_seconds(),
        classification=None,
        exception=None,
        result=None,
        decision=None,
        stop_reason=None,
        cause=None,
        sleep_s=None,
    )
    hook(ctx)


def _call_attempt_end(
    hook: AttemptHook | None,
    *,
    state: _RetryState,
    attempt: int,
    classification: Classification | None,
    exception: BaseException | None,
    result: Any | None,
    decision: AttemptDecision,
    stop_reason: StopReason | None,
    cause: FailureCause | None,
    sleep_s: float | None,
) -> None:
    if hook is None:
        return
    ctx = AttemptContext(
        attempt=attempt,
        operation=state.operation,
        elapsed_s=state.elapsed().total_seconds(),
        classification=classification,
        exception=exception,
        result=result,
        decision=decision,
        stop_reason=stop_reason,
        cause=cause,
        sleep_s=sleep_s,
    )
    hook(ctx)


def _call_attempt_end_from_outcome(
    hook: AttemptHook | None,
    *,
    state: _RetryState,
    attempt: int,
    outcome: _AttemptOutcome,
) -> None:
    _call_attempt_end(
        hook,
        state=state,
        attempt=attempt,
        classification=outcome.classification,
        exception=outcome.exception,
        result=outcome.result,
        decision=outcome.decision,
        stop_reason=outcome.stop_reason,
        cause=outcome.cause,
        sleep_s=outcome.sleep_s,
    )


def _finalize_attempt(
    *,
    state: _RetryState,
    attempt: int,
    decision: _RetryDecision,
    sleep_action: SleepDecision | None,
    classification: Classification | None,
    exception: BaseException | None,
    result: Any | None,
    cause: FailureCause | None,
) -> _AttemptOutcome:
    if decision.action == "raise":
        return _AttemptOutcome(
            decision=AttemptDecision.RAISE,
            classification=classification,
            exception=exception,
            result=result,
            cause=cause,
            stop_reason=state.last_stop_reason,
            sleep_s=None,
        )

    if sleep_action is SleepDecision.DEFER:
        return _AttemptOutcome(
            decision=AttemptDecision.SCHEDULED,
            classification=classification,
            exception=exception,
            result=result,
            cause=cause,
            stop_reason=StopReason.SCHEDULED,
            sleep_s=decision.sleep_s,
        )

    if sleep_action is SleepDecision.ABORT:
        return _AttemptOutcome(
            decision=AttemptDecision.ABORTED,
            classification=classification,
            exception=exception,
            result=result,
            cause=cause,
            stop_reason=StopReason.ABORTED,
            sleep_s=None,
        )

    if state.elapsed() > state.policy.deadline:
        state.last_stop_reason = StopReason.DEADLINE_EXCEEDED
        state.emit(
            EventName.DEADLINE_EXCEEDED.value,
            attempt,
            0.0,
            state.last_class,
            exception,
            stop_reason=StopReason.DEADLINE_EXCEEDED,
            cause=cause,
        )
        return _AttemptOutcome(
            decision=AttemptDecision.RAISE,
            classification=classification,
            exception=exception,
            result=result,
            cause=cause,
            stop_reason=StopReason.DEADLINE_EXCEEDED,
            sleep_s=None,
        )

    if attempt == state.policy.max_attempts:
        state.last_stop_reason = StopReason.MAX_ATTEMPTS_GLOBAL
        state.emit(
            EventName.MAX_ATTEMPTS_EXCEEDED.value,
            attempt,
            0.0,
            state.last_class,
            exception,
            stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
            cause=cause,
        )
        return _AttemptOutcome(
            decision=AttemptDecision.RAISE,
            classification=classification,
            exception=exception,
            result=result,
            cause=cause,
            stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
            sleep_s=None,
        )

    return _AttemptOutcome(
        decision=AttemptDecision.RETRY,
        classification=classification,
        exception=exception,
        result=result,
        cause=cause,
        stop_reason=None,
        sleep_s=decision.sleep_s,
    )


def _sync_failure_outcome(
    *,
    state: _RetryState,
    attempt: int,
    decision: _RetryDecision,
    classification: Classification | None,
    exception: BaseException | None,
    result: Any | None,
    cause: FailureCause | None,
    sleep_fn: SleepFn | None,
) -> _AttemptOutcome:
    if decision.action == "raise":
        return _finalize_attempt(
            state=state,
            attempt=attempt,
            decision=decision,
            sleep_action=None,
            classification=classification,
            exception=exception,
            result=result,
            cause=cause,
        )

    sleep_action = _sync_sleep_action(
        state=state,
        attempt=attempt,
        decision=decision,
        sleep_fn=sleep_fn,
    )
    return _finalize_attempt(
        state=state,
        attempt=attempt,
        decision=decision,
        sleep_action=sleep_action,
        classification=classification,
        exception=exception,
        result=result,
        cause=cause,
    )


async def _async_failure_outcome(
    *,
    state: _RetryState,
    attempt: int,
    decision: _RetryDecision,
    classification: Classification | None,
    exception: BaseException | None,
    result: Any | None,
    cause: FailureCause | None,
    sleep_fn: SleepFn | None,
) -> _AttemptOutcome:
    if decision.action == "raise":
        return _finalize_attempt(
            state=state,
            attempt=attempt,
            decision=decision,
            sleep_action=None,
            classification=classification,
            exception=exception,
            result=result,
            cause=cause,
        )

    sleep_action = await _async_sleep_action(
        state=state,
        attempt=attempt,
        decision=decision,
        sleep_fn=sleep_fn,
    )
    return _finalize_attempt(
        state=state,
        attempt=attempt,
        decision=decision,
        sleep_action=sleep_action,
        classification=classification,
        exception=exception,
        result=result,
        cause=cause,
    )


def _sync_sleep_action(
    *,
    state: _RetryState,
    attempt: int,
    decision: _RetryDecision,
    sleep_fn: SleepFn | None,
) -> SleepDecision:
    if sleep_fn is None:
        time.sleep(decision.sleep_s)
        return SleepDecision.SLEEP

    ctx = decision.context
    if ctx is None:
        raise RuntimeError("Missing BackoffContext for sleep decision.")

    action = sleep_fn(ctx, decision.sleep_s)
    if action is SleepDecision.SLEEP:
        time.sleep(decision.sleep_s)
        return action
    if action is SleepDecision.DEFER:
        state.last_stop_reason = StopReason.SCHEDULED
        state.emit(
            EventName.SCHEDULED.value,
            attempt,
            decision.sleep_s,
            state.last_class,
            state.last_exc,
            stop_reason=StopReason.SCHEDULED,
            cause=state.last_cause,
        )
        return action
    if action is SleepDecision.ABORT:
        if state.last_stop_reason is not StopReason.ABORTED:
            state.last_stop_reason = StopReason.ABORTED
            state.emit(
                EventName.ABORTED.value,
                attempt,
                0.0,
                stop_reason=StopReason.ABORTED,
            )
        return action
    raise ValueError("sleep handler must return a SleepDecision.")


async def _async_sleep_action(
    *,
    state: _RetryState,
    attempt: int,
    decision: _RetryDecision,
    sleep_fn: SleepFn | None,
) -> SleepDecision:
    if sleep_fn is None:
        await asyncio.sleep(decision.sleep_s)
        return SleepDecision.SLEEP

    ctx = decision.context
    if ctx is None:
        raise RuntimeError("Missing BackoffContext for sleep decision.")

    action = sleep_fn(ctx, decision.sleep_s)
    if action is SleepDecision.SLEEP:
        await asyncio.sleep(decision.sleep_s)
        return action
    if action is SleepDecision.DEFER:
        state.last_stop_reason = StopReason.SCHEDULED
        state.emit(
            EventName.SCHEDULED.value,
            attempt,
            decision.sleep_s,
            state.last_class,
            state.last_exc,
            stop_reason=StopReason.SCHEDULED,
            cause=state.last_cause,
        )
        return action
    if action is SleepDecision.ABORT:
        if state.last_stop_reason is not StopReason.ABORTED:
            state.last_stop_reason = StopReason.ABORTED
            state.emit(
                EventName.ABORTED.value,
                attempt,
                0.0,
                stop_reason=StopReason.ABORTED,
            )
        return action
    raise ValueError("sleep handler must return a SleepDecision.")
