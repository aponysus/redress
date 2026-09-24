"""Lifecycle observers must not change operation execution or terminal outcomes."""

import asyncio

import pytest

from redress import (
    AbortRetry,
    AsyncPolicy,
    AsyncRetry,
    AsyncRetryPolicy,
    Budget,
    CircuitBreaker,
    ErrorClass,
    Policy,
    Retry,
    RetryPolicy,
)
from redress.testing import instant_retries


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("method", ["call", "execute"])
@pytest.mark.parametrize("kind", ["policy", "component", "wrapper", "no_retry"])
@pytest.mark.parametrize("failing_hook", ["start", "end"])
@pytest.mark.parametrize(
    "scenario",
    [
        "success",
        "recover_exception",
        "terminal_exception",
        "recover_result",
        "terminal_result",
        "abort",
    ],
)
def test_hook_failure_preserves_execution(is_async, method, kind, failing_hook, scenario):
    original_error = TimeoutError("operation failed")
    abort_error = AbortRetry()
    bad_result = object()
    good_result = object()

    def run(fail_hook):
        operation_calls = []
        hooks = []
        events = []
        budget = Budget(max_retries=5, window_s=60)
        breaker = CircuitBreaker(failure_threshold=1)

        def classifier(exc):
            assert exc is original_error  # Observer errors must never reach classification.
            return ErrorClass.TRANSIENT

        def result_classifier(value):
            return ErrorClass.TRANSIENT if value is bad_result else None

        config = dict(
            classifier=classifier,
            result_classifier=result_classifier,
            strategy=instant_retries,
            max_attempts=2,
            budget=budget,
        )
        retry_type = AsyncRetry if is_async else Retry
        policy_type = AsyncPolicy if is_async else Policy
        wrapper_type = AsyncRetryPolicy if is_async else RetryPolicy
        if kind == "policy":
            policy = policy_type(retry=retry_type(**config), circuit_breaker=breaker)
        elif kind == "component":
            policy = retry_type(**config)
        elif kind == "wrapper":
            policy = wrapper_type(**config)
        else:
            policy = policy_type(circuit_breaker=breaker)

        def operation():
            operation_calls.append(None)
            if scenario == "abort":
                raise abort_error
            if scenario == "terminal_exception" or (
                scenario == "recover_exception" and len(operation_calls) == 1
            ):
                raise original_error
            if scenario == "terminal_result" or (
                scenario == "recover_result" and len(operation_calls) == 1
            ):
                return bad_result
            return good_result

        async def async_operation():
            return operation()

        def observer(phase, ctx):
            hooks.append((phase, ctx.attempt, ctx.decision, ctx.stop_reason))
            if fail_hook and phase == failing_hook:
                raise TimeoutError("observer unavailable")

        kwargs = dict(
            on_attempt_start=lambda ctx: observer("start", ctx),
            on_attempt_end=lambda ctx: observer("end", ctx),
            on_metric=lambda event, attempt, delay, tags: events.append((event, attempt, tags)),
        )
        try:
            result = getattr(policy, method)(async_operation if is_async else operation, **kwargs)
            if is_async:
                result = asyncio.run(result)
        except Exception as exc:
            if hasattr(exc, "stop_reason"):
                terminal = (type(exc), exc.stop_reason, exc.attempts, exc.last_result)
            else:
                terminal = ("exception", exc)
        else:
            if method == "execute":
                terminal = (
                    result.ok,
                    result.value,
                    result.stop_reason,
                    result.attempts,
                    result.last_exception,
                    result.last_result,
                )
            else:
                terminal = ("value", result)
        return len(operation_calls), terminal, hooks, events, budget.remaining(), breaker.state

    baseline = run(False)
    observed = run(True)
    assert observed == baseline
    if scenario == "success":
        assert observed[0] == 1  # A successful side effect is never repeated for a hook failure.


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("method", ["call", "execute"])
@pytest.mark.parametrize("with_retry", [False, True])
@pytest.mark.parametrize("phase", ["start", "end"])
@pytest.mark.parametrize("error_type", [asyncio.CancelledError, KeyboardInterrupt, SystemExit])
def test_lifecycle_hooks_preserve_base_exceptions(is_async, method, with_retry, phase, error_type):
    error = error_type()
    calls = []
    retry_type = AsyncRetry if is_async else Retry
    policy_type = AsyncPolicy if is_async else Policy
    policy = policy_type(
        retry=(
            retry_type(
                classifier=lambda exc: ErrorClass.TRANSIENT,
                strategy=instant_retries,
                max_attempts=3,
            )
            if with_retry
            else None
        )
    )

    def operation():
        calls.append(None)
        return "ok"

    async def async_operation():
        return operation()

    def hook(ctx):
        raise error

    kwargs = {f"on_attempt_{phase}": hook}

    async def invoke_async():
        # Catch inside the coroutine so KeyboardInterrupt/SystemExit do not reach
        # asyncio.run's own task cleanup machinery during this assertion.
        try:
            await getattr(policy, method)(async_operation, **kwargs)
        except BaseException as exc:
            return exc
        return None

    if is_async:
        assert asyncio.run(invoke_async()) is error
    else:
        with pytest.raises(error_type) as caught:
            getattr(policy, method)(operation, **kwargs)
        assert caught.value is error
    assert len(calls) == (0 if phase == "start" else 1)


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("hook_error", [TimeoutError, AbortRetry])
def test_first_success_hook_failure_never_repeats_operation(is_async, hook_error):
    calls = []
    observed = []
    retry_type = AsyncRetry if is_async else Retry
    policy_type = AsyncPolicy if is_async else Policy
    policy = policy_type(
        retry=retry_type(
            classifier=lambda exc: ErrorClass.TRANSIENT,
            strategy=instant_retries,
            max_attempts=3,
        )
    )

    def operation():
        calls.append("side effect")
        return "ok"

    async def async_operation():
        return operation()

    def on_end(ctx):
        observed.append(ctx)
        if len(observed) == 1:
            raise hook_error("observer failed once")

    outcome = policy.execute(async_operation if is_async else operation, on_attempt_end=on_end)
    if is_async:
        outcome = asyncio.run(outcome)
    assert outcome.ok and outcome.value == "ok"
    assert outcome.attempts == 1
    assert calls == ["side effect"]
    assert len(observed) == 1
