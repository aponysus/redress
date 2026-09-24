"""Exhaustion must not schedule work when there is no next attempt."""

import asyncio

import pytest

from redress import (
    AsyncPolicy,
    AsyncRetry,
    Budget,
    ErrorClass,
    Policy,
    Retry,
    RetryExhaustedError,
    SleepDecision,
    StopReason,
)
from redress.policy import AttemptDecision


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("method", ["call", "execute"])
@pytest.mark.parametrize("failure", ["exception", "result"])
@pytest.mark.parametrize("max_attempts", [1, 3])
@pytest.mark.parametrize("spare_tokens", [0, 1])
def test_exhaustion_does_not_schedule_another_retry(
    is_async, method, failure, max_attempts, spare_tokens
):
    calls = []
    delays = []
    strategies = []
    before_sleeps = []
    events = []
    ends = []
    error = TimeoutError("unavailable")
    failed_result = object()
    budget = Budget(max_retries=max_attempts - 1 + spare_tokens, window_s=60)

    def operation():
        calls.append(None)
        if failure == "exception":
            raise error
        return failed_result

    async def async_operation():
        return operation()

    def strategy(ctx):
        strategies.append(ctx.attempt)
        return 0.1

    def sleeper(delay):
        delays.append(delay)

    retry_type = AsyncRetry if is_async else Retry
    policy_type = AsyncPolicy if is_async else Policy
    policy = policy_type(
        retry=retry_type(
            classifier=lambda exc: ErrorClass.TRANSIENT,
            result_classifier=lambda result: ErrorClass.TRANSIENT,
            strategy=strategy,
            max_attempts=max_attempts,
            budget=budget,
            sleeper=sleeper,
        )
    )

    def invoke():
        kwargs = {
            "before_sleep": lambda ctx, delay: before_sleeps.append(ctx.attempt),
            "on_metric": lambda event, attempt, delay, tags: events.append((event, attempt)),
            "on_attempt_end": ends.append,
        }
        if method == "execute":
            kwargs["capture_timeline"] = True
        result = getattr(policy, method)(async_operation if is_async else operation, **kwargs)
        return asyncio.run(result) if is_async else result

    if method == "execute":
        outcome = invoke()
        assert not outcome.ok
        assert outcome.stop_reason is StopReason.MAX_ATTEMPTS_GLOBAL
        assert outcome.attempts == max_attempts
        assert outcome.last_exception is (error if failure == "exception" else None)
        assert outcome.last_result is (failed_result if failure == "result" else None)
        assert outcome.next_sleep_s is None
        assert outcome.timeline.events[-1].stop_reason is StopReason.MAX_ATTEMPTS_GLOBAL
    elif failure == "exception":
        with pytest.raises(TimeoutError) as caught:
            invoke()
        assert caught.value is error
    else:
        with pytest.raises(RetryExhaustedError) as caught:
            invoke()
        assert caught.value.stop_reason is StopReason.MAX_ATTEMPTS_GLOBAL
        assert caught.value.attempts == max_attempts
        assert caught.value.last_result is failed_result

    assert len(calls) == max_attempts
    assert strategies == list(range(1, max_attempts))
    assert before_sleeps == list(range(1, max_attempts))
    assert delays == [0.1] * (max_attempts - 1)
    assert budget.remaining() == spare_tokens
    assert events == [
        *[("retry", attempt) for attempt in range(1, max_attempts)],
        ("max_attempts_exceeded", max_attempts),
    ]
    assert len(ends) == max_attempts
    assert ends[-1].decision is AttemptDecision.RAISE
    assert ends[-1].stop_reason is StopReason.MAX_ATTEMPTS_GLOBAL
    assert ends[-1].sleep_s is None


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("decision", [SleepDecision.DEFER, SleepDecision.ABORT])
def test_terminal_attempt_does_not_invoke_sleep_handler(is_async, decision):
    def operation():
        raise TimeoutError("unavailable")

    async def async_operation():
        operation()

    sleeps = []

    def sleep(ctx, delay):
        sleeps.append(delay)
        return decision

    retry_type = AsyncRetry if is_async else Retry
    policy_type = AsyncPolicy if is_async else Policy
    policy = policy_type(
        retry=retry_type(
            classifier=lambda exc: ErrorClass.TRANSIENT,
            strategy=lambda ctx: 0.1,
            max_attempts=1,
            sleep=sleep,
        )
    )
    result = policy.execute(async_operation if is_async else operation)
    outcome = asyncio.run(result) if is_async else result
    assert outcome.stop_reason is StopReason.MAX_ATTEMPTS_GLOBAL
    assert outcome.next_sleep_s is None
    assert sleeps == []
