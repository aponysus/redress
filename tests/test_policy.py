# tests/test_policy.py


import importlib
import time
import traceback
from typing import Any

import pytest

from redress import Budget, SleepDecision
from redress.circuit import CircuitBreaker, CircuitState
from redress.classify import Classification, default_classifier
from redress.config import RetryConfig
from redress.errors import (
    AbortRetryError,
    CircuitOpenError,
    ErrorClass,
    PermanentError,
    RateLimitError,
    RetryExhaustedError,
    StopReason,
)
from redress.events import EventName
from redress.policy import AttemptDecision, MetricHook, Policy, Retry, RetryPolicy, RetryTimeline
from redress.strategies import BackoffContext, decorrelated_jitter
from redress.testing import instant_retries

_retry_mod = importlib.import_module("redress.policy.retry_helpers")
_state_mod = importlib.import_module("redress.policy.state")


class _FakeTime:
    """
    Simple fake monotonic clock to control time in deadline tests.
    """

    def __init__(self, start: float | None = None) -> None:
        self._now = start or 0.0

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_metrics() -> tuple[MetricHook, list[tuple[str, int, float, dict[str, Any]]]]:
    """
    Return a metric_hook and a list that captures all metric calls.
    """
    events: list[tuple[str, int, float, dict[str, Any]]] = []

    def hook(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        events.append((event, attempt, sleep_s, tags))

    return hook, events


def _collect_logs() -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
    """
    Return a log_hook and a list that captures all log calls.
    """
    events: list[tuple[str, dict[str, Any]]] = []

    def hook(event: str, fields: dict[str, Any]) -> None:
        events.append((event, fields))

    return hook, events


def _assert_tb_has_frame(err: BaseException, func_name: str) -> None:
    tb = err.__traceback__
    assert tb is not None
    frames = traceback.extract_tb(tb)
    assert any(frame.name == func_name for frame in frames)


# ---------------------------------------------------------------------------
# Basic behavior tests
# ---------------------------------------------------------------------------


def test_permanent_error_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    PERMANENT errors should not be retried, and should emit 'permanent_fail'.
    """
    call_count = {"n": 0}

    def func() -> None:
        call_count["n"] += 1
        raise PermanentError("do not retry me")

    metric_hook, events = _collect_metrics()

    # Ensure we don't actually sleep during test
    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=1.0),
        deadline_s=30.0,
        max_attempts=5,
    )

    with pytest.raises(PermanentError) as excinfo:
        policy.call(func, on_metric=metric_hook)

    _assert_tb_has_frame(excinfo.value, func.__name__)

    # Only one attempt
    assert call_count["n"] == 1


def test_attempt_hooks_retry_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []
    attempt_count = {"n": 0}

    def on_start(ctx: Any) -> None:
        calls.append(("start", ctx))

    def on_end(ctx: Any) -> None:
        calls.append(("end", ctx))

    def func() -> str:
        attempt_count["n"] += 1
        if attempt_count["n"] == 1:
            raise RuntimeError("boom")
        return "ok"

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    policy = RetryPolicy(
        classifier=lambda exc: ErrorClass.TRANSIENT,
        strategy=instant_retries,
        max_attempts=3,
    )

    result = policy.call(func, on_attempt_start=on_start, on_attempt_end=on_end)
    assert result == "ok"
    assert [entry[0] for entry in calls] == ["start", "end", "start", "end"]

    start1 = calls[0][1]
    end1 = calls[1][1]
    end2 = calls[3][1]

    assert start1.attempt == 1
    assert start1.decision is None
    assert start1.classification is None

    assert end1.decision is AttemptDecision.RETRY
    assert end1.classification is not None
    assert end1.classification.klass is ErrorClass.TRANSIENT
    assert end1.cause == "exception"
    assert end1.sleep_s == 0.0

    assert end2.attempt == 2
    assert end2.decision is AttemptDecision.SUCCESS
    assert end2.result == "ok"
    assert end2.classification is None


def test_policy_accepts_legacy_strategy_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"n": 0}

    def func() -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RateLimitError("429")
        return "ok"

    def legacy_strategy(attempt: int, klass: ErrorClass, prev: float | None) -> float:
        return 0.0

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=legacy_strategy,
        max_attempts=2,
    )

    assert policy.call(func) == "ok"
    assert attempts["n"] == 2


def test_policy_attempt_hooks_without_retry() -> None:
    calls: list[tuple[str, Any]] = []

    def on_start(ctx: Any) -> None:
        calls.append(("start", ctx))

    def on_end(ctx: Any) -> None:
        calls.append(("end", ctx))

    policy = Policy(retry=None)
    result = policy.call(lambda: "ok", on_attempt_start=on_start, on_attempt_end=on_end)
    assert result == "ok"
    assert [entry[0] for entry in calls] == ["start", "end"]

    start_ctx = calls[0][1]
    end_ctx = calls[1][1]
    assert start_ctx.attempt == 1
    assert start_ctx.decision is None
    assert end_ctx.decision is AttemptDecision.SUCCESS
    assert end_ctx.result == "ok"


def test_policy_abort_if_stops_before_attempt() -> None:
    calls = {"func": 0, "classifier": 0}

    def func() -> None:
        calls["func"] += 1
        raise RuntimeError("boom")

    def classifier(_: BaseException) -> ErrorClass:
        calls["classifier"] += 1
        return ErrorClass.TRANSIENT

    metric_hook, events = _collect_metrics()

    policy = RetryPolicy(
        classifier=classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=3,
    )

    with pytest.raises(AbortRetryError):
        policy.call(func, on_metric=metric_hook, abort_if=lambda: True)

    assert calls["func"] == 0
    assert calls["classifier"] == 0
    assert len(events) == 1
    event, attempt, sleep_s, tags = events[0]
    assert event == "aborted"
    assert attempt == 0
    assert sleep_s == 0.0
    assert tags["stop_reason"] == StopReason.ABORTED.value


def test_policy_abort_if_skips_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"func": 0}

    def func() -> None:
        calls["func"] += 1
        raise RateLimitError("429")

    checks = iter([False, False, True])

    def abort_if() -> bool:
        return next(checks)

    slept = {"called": False}

    def fake_sleep(_: float) -> None:
        slept["called"] = True

    monkeypatch.setattr(_retry_mod.time, "sleep", fake_sleep)

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=lambda ctx: 1.0,
        deadline_s=5.0,
        max_attempts=3,
    )

    with pytest.raises(AbortRetryError):
        policy.call(func, abort_if=abort_if)

    assert calls["func"] == 1
    assert slept["called"] is False


def test_policy_execute_success_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def func() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError("429")
        return "ok"

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda _: None)

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=5,
    )

    outcome = policy.execute(func)
    assert outcome.ok is True
    assert outcome.value == "ok"
    assert outcome.attempts == 3
    assert outcome.stop_reason is None


def test_policy_execute_timeline_success_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def func() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError("429")
        return "ok"

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda _: None)

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=5,
    )

    timeline = RetryTimeline()
    outcome = policy.execute(func, capture_timeline=timeline)
    assert outcome.ok is True
    assert outcome.timeline is timeline
    assert timeline.events[-1].event == EventName.SUCCESS.value
    assert any(event.event == EventName.RETRY.value for event in timeline.events)
    retry_event = next(event for event in timeline.events if event.event == EventName.RETRY.value)
    assert retry_event.error_class == ErrorClass.RATE_LIMIT
    assert retry_event.cause == "exception"


def test_policy_execute_stop_reason_permanent() -> None:
    def func() -> None:
        raise PermanentError("stop")

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=3,
    )

    outcome = policy.execute(func)
    assert outcome.ok is False
    assert outcome.stop_reason == StopReason.NON_RETRYABLE_CLASS
    assert outcome.attempts == 1
    assert outcome.last_class == ErrorClass.PERMANENT
    assert isinstance(outcome.last_exception, PermanentError)


def test_policy_execute_stop_reason_per_class_cap() -> None:
    def func() -> None:
        raise RuntimeError("boom")

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=instant_retries,
        per_class_max_attempts={ErrorClass.TRANSIENT: 0},
        deadline_s=5.0,
        max_attempts=3,
    )

    outcome = policy.execute(func)
    assert outcome.ok is False
    assert outcome.stop_reason == StopReason.MAX_ATTEMPTS_PER_CLASS
    assert outcome.attempts == 1
    assert outcome.last_class == ErrorClass.TRANSIENT


def test_policy_execute_stop_reason_unknown_cap() -> None:
    def func() -> None:
        raise RuntimeError("boom")

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.UNKNOWN

    policy = RetryPolicy(
        classifier=classifier,
        strategy=instant_retries,
        max_unknown_attempts=0,
        deadline_s=5.0,
        max_attempts=3,
    )

    outcome = policy.execute(func)
    assert outcome.ok is False
    assert outcome.stop_reason == StopReason.MAX_UNKNOWN_ATTEMPTS
    assert outcome.attempts == 1
    assert outcome.last_class == ErrorClass.UNKNOWN


def test_policy_execute_stop_reason_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeTime(0.0)
    monkeypatch.setattr(_state_mod.time, "monotonic", clock.monotonic)

    def func() -> None:
        clock.advance(2.0)
        raise RateLimitError("429")

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=1.0,
        max_attempts=3,
    )

    outcome = policy.execute(func)
    assert outcome.ok is False
    assert outcome.stop_reason == StopReason.DEADLINE_EXCEEDED
    assert outcome.attempts == 1


def test_policy_execute_stop_reason_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_retry_mod.time, "sleep", lambda _: None)

    def func() -> None:
        raise RateLimitError("429")

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=1,
    )

    outcome = policy.execute(func)
    assert outcome.ok is False
    assert outcome.stop_reason == StopReason.MAX_ATTEMPTS_GLOBAL
    assert outcome.attempts == 1


def test_policy_execute_stop_reason_no_strategy() -> None:
    def func() -> None:
        raise RuntimeError("boom")

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=None,
        strategies={ErrorClass.RATE_LIMIT: instant_retries},
        deadline_s=5.0,
        max_attempts=3,
    )

    outcome = policy.execute(func)
    assert outcome.ok is False
    assert outcome.stop_reason == StopReason.NO_STRATEGY
    assert outcome.attempts == 1


def test_policy_execute_stop_reason_aborted() -> None:
    def func() -> None:
        raise RuntimeError("boom")

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=3,
    )

    outcome = policy.execute(func, abort_if=lambda: True)
    assert outcome.ok is False
    assert outcome.stop_reason == StopReason.ABORTED
    assert outcome.attempts == 0


def test_policy_execute_abort_error_sets_stop_reason() -> None:
    def func() -> None:
        raise AbortRetryError()

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=3,
    )

    outcome = policy.execute(func)
    assert outcome.ok is False
    assert outcome.stop_reason == StopReason.ABORTED


def test_policy_execute_timeline_stop_reason_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeTime(0.0)
    monkeypatch.setattr(_state_mod.time, "monotonic", clock.monotonic)

    def func() -> None:
        clock.advance(2.0)
        raise RateLimitError("429")

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=1.0,
        max_attempts=3,
    )

    outcome = policy.execute(func, capture_timeline=True)
    assert outcome.stop_reason == StopReason.DEADLINE_EXCEEDED
    assert outcome.timeline is not None
    assert any(
        event.event == EventName.DEADLINE_EXCEEDED.value
        and event.stop_reason == StopReason.DEADLINE_EXCEEDED
        for event in outcome.timeline.events
    )


def test_policy_execute_timeline_stop_reason_no_strategy() -> None:
    def func() -> None:
        raise RuntimeError("boom")

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=None,
        strategies={ErrorClass.RATE_LIMIT: instant_retries},
        deadline_s=5.0,
        max_attempts=3,
    )

    outcome = policy.execute(func, capture_timeline=True)
    assert outcome.stop_reason == StopReason.NO_STRATEGY
    assert outcome.timeline is not None
    assert any(
        event.event == EventName.NO_STRATEGY_CONFIGURED.value
        and event.stop_reason == StopReason.NO_STRATEGY
        for event in outcome.timeline.events
    )


def test_policy_execute_timeline_stop_reason_aborted() -> None:
    def func() -> None:
        raise RuntimeError("boom")

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=3,
    )

    outcome = policy.execute(func, abort_if=lambda: True, capture_timeline=True)
    assert outcome.stop_reason == StopReason.ABORTED
    assert outcome.timeline is not None
    assert any(
        event.event == EventName.ABORTED.value and event.stop_reason == StopReason.ABORTED
        for event in outcome.timeline.events
    )


def test_policy_execute_timeline_stop_reason_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_retry_mod.time, "sleep", lambda _: None)

    def func() -> None:
        raise RateLimitError("429")

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=1,
    )

    outcome = policy.execute(func, capture_timeline=True)
    assert outcome.stop_reason == StopReason.MAX_ATTEMPTS_GLOBAL
    assert outcome.timeline is not None
    assert any(
        event.event == EventName.MAX_ATTEMPTS_EXCEEDED.value
        and event.stop_reason == StopReason.MAX_ATTEMPTS_GLOBAL
        for event in outcome.timeline.events
    )


def test_policy_sleep_handler_defers_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    def func() -> None:
        raise RuntimeError("boom")

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    sleep_calls: list[float] = []
    contexts: list[BackoffContext] = []
    before_calls: list[tuple[ErrorClass, float]] = []

    def sleep_fn(ctx: BackoffContext, sleep_s: float) -> SleepDecision:
        contexts.append(ctx)
        sleep_calls.append(sleep_s)
        return SleepDecision.DEFER

    def before_sleep(ctx: BackoffContext, sleep_s: float) -> None:
        before_calls.append((ctx.classification.klass, sleep_s))

    def fail_sleep(_: float) -> None:
        raise AssertionError("sleep should not be called for DEFER")

    monkeypatch.setattr(_retry_mod.time, "sleep", fail_sleep)
    metric_hook, events = _collect_metrics()

    policy = RetryPolicy(
        classifier=classifier,
        strategy=lambda ctx: 1.5,
        deadline_s=5.0,
        max_attempts=3,
    )

    outcome = policy.execute(func, on_metric=metric_hook, sleep=sleep_fn, before_sleep=before_sleep)
    assert outcome.ok is False
    assert outcome.stop_reason == StopReason.SCHEDULED
    assert outcome.next_sleep_s == 1.5
    assert sleep_calls == [1.5]
    assert contexts[0].classification.klass is ErrorClass.TRANSIENT
    assert before_calls == []

    scheduled = next(event for event in events if event[0] == EventName.SCHEDULED.value)
    assert scheduled[3]["stop_reason"] == StopReason.SCHEDULED.value


def test_policy_sleep_handler_defers_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def func() -> None:
        raise RuntimeError("boom")

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    def sleep_fn(ctx: BackoffContext, sleep_s: float) -> SleepDecision:
        assert ctx.classification.klass is ErrorClass.TRANSIENT
        assert sleep_s == 2.0
        return SleepDecision.DEFER

    def fail_sleep(_: float) -> None:
        raise AssertionError("sleep should not be called for DEFER")

    monkeypatch.setattr(_retry_mod.time, "sleep", fail_sleep)

    policy = RetryPolicy(
        classifier=classifier,
        strategy=lambda ctx: 2.0,
        deadline_s=5.0,
        max_attempts=3,
    )

    with pytest.raises(RetryExhaustedError) as excinfo:
        policy.call(func, sleep=sleep_fn)

    err = excinfo.value
    assert err.stop_reason is StopReason.SCHEDULED
    assert err.next_sleep_s == 2.0
    assert isinstance(err.last_exception, RuntimeError)


def test_policy_sleep_handler_aborts_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def func() -> None:
        raise RuntimeError("boom")

    def sleep_fn(_: BackoffContext, __: float) -> SleepDecision:
        return SleepDecision.ABORT

    def fail_sleep(_: float) -> None:
        raise AssertionError("sleep should not be called for ABORT")

    monkeypatch.setattr(_retry_mod.time, "sleep", fail_sleep)

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=lambda ctx: 1.0,
        deadline_s=5.0,
        max_attempts=3,
    )

    with pytest.raises(AbortRetryError):
        policy.call(func, sleep=sleep_fn)


def test_policy_sleep_handler_sleeps_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    def func() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return "ok"

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    def sleep_fn(_: BackoffContext, sleep_s: float) -> SleepDecision:
        return SleepDecision.SLEEP

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: sleeps.append(s))

    policy = RetryPolicy(
        classifier=classifier,
        strategy=lambda ctx: 0.2,
        deadline_s=5.0,
        max_attempts=3,
    )

    result = policy.call(func, sleep=sleep_fn)
    assert result == "ok"
    assert sleeps == [0.2]


def test_policy_custom_sleeper_used(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    sleep_calls: list[float] = []

    def func() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return "ok"

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    def sleeper(seconds: float) -> None:
        sleep_calls.append(seconds)

    def fail_sleep(_: float) -> None:
        raise AssertionError("time.sleep should not be called")

    monkeypatch.setattr(_retry_mod.time, "sleep", fail_sleep)

    policy = RetryPolicy(
        classifier=classifier,
        strategy=lambda ctx: 0.2,
        deadline_s=5.0,
        max_attempts=3,
    )

    result = policy.call(func, sleeper=sleeper)
    assert result == "ok"
    assert sleep_calls == [0.2]


def test_policy_budget_exhausted_execute() -> None:
    def func() -> None:
        raise RuntimeError("boom")

    budget = Budget(max_retries=1, window_s=60.0)
    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=5,
        budget=budget,
    )

    outcome = policy.execute(func, capture_timeline=True)
    assert outcome.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert outcome.attempts == 2
    assert outcome.timeline is not None
    assert any(event.event == EventName.BUDGET_EXHAUSTED.value for event in outcome.timeline.events)


def test_policy_budget_shared_across_policies() -> None:
    def func() -> None:
        raise RuntimeError("boom")

    budget = Budget(max_retries=1, window_s=60.0)
    policy_one = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=5,
        budget=budget,
    )
    policy_two = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=5,
        budget=budget,
    )

    outcome_one = policy_one.execute(func)
    outcome_two = policy_two.execute(func)

    assert outcome_one.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert outcome_one.attempts == 2
    assert outcome_two.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert outcome_two.attempts == 1


def test_policy_attempt_timeout_execute() -> None:
    def func() -> str:
        time.sleep(0.05)
        return "ok"

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=1.0,
        max_attempts=1,
        attempt_timeout_s=0.01,
    )

    outcome = policy.execute(func)
    assert outcome.stop_reason is StopReason.MAX_ATTEMPTS_GLOBAL
    assert isinstance(outcome.last_exception, TimeoutError)
    assert outcome.last_class is ErrorClass.TRANSIENT


def test_policy_before_sleep_hook_called(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    before_calls: list[tuple[ErrorClass, float]] = []

    def func() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return "ok"

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    def before_sleep(ctx: BackoffContext, sleep_s: float) -> None:
        before_calls.append((ctx.classification.klass, sleep_s))

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda _: None)

    policy = RetryPolicy(
        classifier=classifier,
        strategy=lambda ctx: 0.2,
        deadline_s=5.0,
        max_attempts=3,
    )

    result = policy.call(func, before_sleep=before_sleep)
    assert result == "ok"
    assert before_calls == [(ErrorClass.TRANSIENT, 0.2)]


def test_sleep_handler_missing_context_raises() -> None:
    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        max_attempts=1,
    )
    state = _state_mod._RetryState(
        policy=policy.retry,
        on_metric=None,
        on_log=None,
        operation=None,
        abort_if=None,
    )
    decision = _state_mod._RetryDecision(action="retry", sleep_s=0.1, context=None)

    with pytest.raises(RuntimeError, match="Missing BackoffContext"):
        _retry_mod._sync_sleep_action(
            state=state,
            attempt=1,
            decision=decision,
            sleep_fn=lambda ctx, sleep_s: SleepDecision.SLEEP,
            before_sleep=None,
            sleeper=None,
        )


def test_policy_execute_result_failure() -> None:
    def func() -> str:
        return "bad"

    def result_classifier(_: str) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=default_classifier,
        result_classifier=result_classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=1,
    )

    outcome = policy.execute(func)
    assert outcome.ok is False
    assert outcome.stop_reason == StopReason.MAX_ATTEMPTS_GLOBAL
    assert outcome.attempts == 1
    assert outcome.cause == "result"
    assert outcome.last_result == "bad"


def test_auth_error_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    AUTH errors should not be retried and emit 'permanent_fail' with class tag.
    """
    call_count = {"n": 0}

    class AuthError(Exception):
        pass

    def func() -> None:
        call_count["n"] += 1
        raise AuthError("no auth")

    metric_hook, events = _collect_metrics()

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.AUTH

    policy = RetryPolicy(
        classifier=classifier,
        strategy=instant_retries,
        deadline_s=30.0,
        max_attempts=5,
    )

    with pytest.raises(AuthError):
        policy.call(func, on_metric=metric_hook)

    assert call_count["n"] == 1
    event, attempt, sleep_s, tags = events[0]
    assert event == EventName.PERMANENT_FAIL.value
    assert attempt == 1
    assert sleep_s == 0.0
    assert tags["class"] == ErrorClass.AUTH.name
    assert tags["err"] == "AuthError"


def test_permission_error_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    PERMISSION errors should not be retried and emit 'permanent_fail' with class tag.
    """
    call_count = {"n": 0}

    class ForbiddenError(Exception):
        pass

    def func() -> None:
        call_count["n"] += 1
        raise ForbiddenError("forbidden")

    metric_hook, events = _collect_metrics()

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.PERMISSION

    policy = RetryPolicy(
        classifier=classifier,
        strategy=instant_retries,
        deadline_s=30.0,
        max_attempts=5,
    )

    with pytest.raises(ForbiddenError):
        policy.call(func, on_metric=metric_hook)

    assert call_count["n"] == 1
    event, attempt, sleep_s, tags = events[0]
    assert event == "permanent_fail"
    assert attempt == 1
    assert sleep_s == 0.0
    assert tags["class"] == ErrorClass.PERMISSION.name
    assert tags["err"] == "ForbiddenError"


def test_context_strategy_receives_classification_from_error_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TransientError(Exception):
        pass

    calls = {"n": 0}
    sleep_calls: list[float] = []

    def func() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientError("boom")
        return "ok"

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    def strategy(ctx: BackoffContext) -> float:
        assert ctx.classification.klass is ErrorClass.TRANSIENT
        assert ctx.classification.retry_after_s is None
        assert ctx.classification.details == {}
        assert ctx.cause == "exception"
        return 0.0

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: sleep_calls.append(s))

    policy = RetryPolicy(
        classifier=classifier,
        strategy=strategy,
        deadline_s=30.0,
        max_attempts=3,
    )

    assert policy.call(func) == "ok"
    assert calls["n"] == 2
    assert sleep_calls == [0.0]


def test_context_strategy_receives_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    class RateLimitError(Exception):
        pass

    calls = {"n": 0}
    sleep_calls: list[float] = []

    def func() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitError("429")
        return "ok"

    def classifier(_: BaseException) -> Classification:
        return Classification(
            klass=ErrorClass.RATE_LIMIT,
            retry_after_s=0.5,
            details={"source": "header"},
        )

    def strategy(ctx: BackoffContext) -> float:
        assert ctx.classification.retry_after_s == 0.5
        assert ctx.classification.details == {"source": "header"}
        return float(ctx.classification.retry_after_s or 0.0)

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: sleep_calls.append(s))

    policy = RetryPolicy(
        classifier=classifier,
        strategy=strategy,
        deadline_s=30.0,
        max_attempts=3,
    )

    assert policy.call(func) == "ok"
    assert calls["n"] == 2
    assert sleep_calls == [0.5]


def test_legacy_strategy_wrapped_for_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    class TransientError(Exception):
        pass

    calls = {"n": 0}
    sleep_calls: list[float] = []

    def func() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientError("boom")
        return "ok"

    def classifier(_: BaseException) -> Classification:
        return Classification(klass=ErrorClass.TRANSIENT, retry_after_s=0.25)

    def strategy(attempt: int, klass: ErrorClass, prev_sleep: float | None) -> float:
        assert klass is ErrorClass.TRANSIENT
        return 0.0

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: sleep_calls.append(s))

    policy = RetryPolicy(
        classifier=classifier,
        strategy=strategy,
        deadline_s=30.0,
        max_attempts=3,
    )

    assert policy.call(func) == "ok"
    assert calls["n"] == 2
    assert sleep_calls == [0.0]


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), -float("inf")])
def test_strategy_invalid_sleep_is_clamped(monkeypatch: pytest.MonkeyPatch, value: float) -> None:
    class TransientError(Exception):
        pass

    sleep_calls: list[float] = []

    def func() -> None:
        raise TransientError("boom")

    metric_hook, events = _collect_metrics()

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    def strategy(ctx: BackoffContext) -> float:
        return value

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: sleep_calls.append(s))

    policy = RetryPolicy(
        classifier=classifier,
        strategy=strategy,
        deadline_s=10.0,
        max_attempts=2,
    )

    with pytest.raises(TransientError):
        policy.call(func, on_metric=metric_hook)

    assert sleep_calls and all(call == 0.0 for call in sleep_calls)
    retry_events = [e for e in events if e[0] == "retry"]
    assert retry_events and all(event[2] == 0.0 for event in retry_events)


def test_missing_strategy_stops_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    class TransientError(Exception):
        pass

    calls = {"n": 0}

    def func() -> None:
        calls["n"] += 1
        raise TransientError("boom")

    metric_hook, events = _collect_metrics()

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    def classifier(_: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=None,
        strategies={ErrorClass.RATE_LIMIT: instant_retries},
        deadline_s=30.0,
        max_attempts=5,
    )

    with pytest.raises(TransientError):
        policy.call(func, on_metric=metric_hook)

    assert calls["n"] == 1
    assert events and events[0][0] == "no_strategy_configured"
    assert events[0][3]["class"] == ErrorClass.TRANSIENT.name
    assert events[0][3]["err"] == "TransientError"
    assert events[0][3]["stop_reason"] == StopReason.NO_STRATEGY.value


def test_keyboard_interrupt_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def func() -> None:
        raise KeyboardInterrupt("stop")

    metric_hook, events = _collect_metrics()

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=30.0,
        max_attempts=3,
    )

    with pytest.raises(KeyboardInterrupt):
        policy.call(func, on_metric=metric_hook)

    assert events == []


def test_system_exit_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def func() -> None:
        raise SystemExit(2)

    metric_hook, events = _collect_metrics()

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        deadline_s=30.0,
        max_attempts=3,
    )

    with pytest.raises(SystemExit):
        policy.call(func, on_metric=metric_hook)

    assert events == []


def test_transient_error_retries_and_uses_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    TRANSIENT errors should be retried using the configured strategy.
    """
    attempts_before_success = 3
    call_count = {"n": 0}

    def func() -> str:
        call_count["n"] += 1
        if call_count["n"] < attempts_before_success:
            # Use a timeout-like name so default_classifier -> TRANSIENT
            class FakeTimeoutError(Exception):
                pass

            raise FakeTimeoutError("temporary")
        return "ok"

    metric_hook, events = _collect_metrics()

    # Track that the strategy was invoked
    strategy_calls: list[tuple[int, ErrorClass, float | None]] = []

    def strategy(attempt: int, klass: ErrorClass, prev_sleep: float | None) -> float:
        strategy_calls.append((attempt, klass, prev_sleep))
        return 0.0

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    # Custom classifier that forces TRANSIENT for our FakeTimeoutError
    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=strategy,
        deadline_s=30.0,
        max_attempts=5,
    )

    result = policy.call(func, on_metric=metric_hook)
    assert result == "ok"

    # We should have called func 3 times: 2 failures + 1 success
    assert call_count["n"] == attempts_before_success

    # Strategy should have been called for each retry (2 times here)
    assert len(strategy_calls) == attempts_before_success - 1
    for i, (attempt, klass, _prev_sleep) in enumerate(strategy_calls, start=1):
        assert attempt == i  # 1, then 2
        assert klass is ErrorClass.TRANSIENT

    # Metrics should have 2 'retry's and 1 'success'
    retry_events = [e for e in events if e[0] == "retry"]
    success_events = [e for e in events if e[0] == "success"]
    assert len(retry_events) == attempts_before_success - 1
    assert len(success_events) == 1


def test_max_attempts_re_raises_last_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    When max_attempts is exceeded, the last exception should be re-raised,
    not a generic RuntimeError.
    """

    class FooError(Exception):
        pass

    call_count = {"n": 0}

    def func() -> None:
        call_count["n"] += 1
        raise FooError("always fails")

    metric_hook, events = _collect_metrics()

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=instant_retries,
        deadline_s=30.0,
        max_attempts=3,
    )

    with pytest.raises(FooError):
        policy.call(func, on_metric=metric_hook)

    assert call_count["n"] == 3  # tried max_attempts times

    # Last metric should be 'max_attempts_exceeded'
    assert events[-1][0] == "max_attempts_exceeded"
    assert events[-1][1] == 3
    assert events[-1][3]["err"] == "FooError"
    assert events[-1][3]["class"] == ErrorClass.TRANSIENT.name
    assert events[-1][3]["stop_reason"] == StopReason.MAX_ATTEMPTS_GLOBAL.value


def test_operation_and_tags_are_emitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Metric tags should include class, err, and operation when available.
    """

    class FlakyError(Exception):
        pass

    calls = {"n": 0}

    def func() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise FlakyError("boom")
        return "ok"

    metric_hook, events = _collect_metrics()

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=instant_retries,
        deadline_s=10.0,
        max_attempts=3,
    )

    result = policy.call(func, on_metric=metric_hook, operation="fetch_profile")
    assert result == "ok"

    retry = next(e for e in events if e[0] == "retry")
    assert retry[3]["class"] == ErrorClass.TRANSIENT.name
    assert retry[3]["err"] == "FlakyError"
    assert retry[3]["operation"] == "fetch_profile"

    success = next(e for e in events if e[0] == "success")
    assert success[3]["operation"] == "fetch_profile"


def test_log_hook_receives_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    on_log should mirror metric emission points with safe fields.
    """

    class FlakyError(Exception):
        pass

    calls = {"n": 0}

    def func() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise FlakyError("boom")
        return "ok"

    log_hook, log_events = _collect_logs()
    metric_hook, _ = _collect_metrics()

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=instant_retries,
        deadline_s=10.0,
        max_attempts=3,
    )

    result = policy.call(func, on_metric=metric_hook, on_log=log_hook, operation="op")
    assert result == "ok"

    event_names = [e[0] for e in log_events]
    assert "retry" in event_names
    assert "success" in event_names

    retry_event = next(e for e in log_events if e[0] == "retry")
    retry_fields = retry_event[1]
    assert retry_fields["class"] == ErrorClass.TRANSIENT.name
    assert retry_fields["err"] == "FlakyError"
    assert retry_fields["operation"] == "op"
    assert retry_fields["attempt"] == 1
    assert retry_fields["sleep_s"] == 0.0


def test_retry_after_logged_only_on_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    class RateLimitError(Exception):
        pass

    calls = {"n": 0}

    def func() -> None:
        calls["n"] += 1
        raise RateLimitError("429")

    log_hook, log_events = _collect_logs()
    metric_hook, metric_events = _collect_metrics()

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    def classifier(_: BaseException) -> Classification:
        return Classification(klass=ErrorClass.RATE_LIMIT, retry_after_s=1.5)

    def strategy(ctx: BackoffContext) -> float:
        return float(ctx.classification.retry_after_s or 0.0)

    policy = RetryPolicy(
        classifier=classifier,
        strategy=strategy,
        deadline_s=10.0,
        max_attempts=2,
    )

    with pytest.raises(RateLimitError):
        policy.call(func, on_metric=metric_hook, on_log=log_hook)

    retry_log = next(e for e in log_events if e[0] == "retry")
    assert retry_log[1]["retry_after_s"] == 1.5

    retry_metric = next(e for e in metric_events if e[0] == "retry")
    assert "retry_after_s" not in retry_metric[3]


def test_hooks_are_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Hook exceptions should not break workload execution.
    """

    class FlakyError(Exception):
        pass

    calls = {"n": 0}

    def func() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise FlakyError("boom")
        return "ok"

    def noisy_metric(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        raise RuntimeError("metric backend down")

    def noisy_log(event: str, fields: dict[str, Any]) -> None:
        raise RuntimeError("log backend down")

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=instant_retries,
        deadline_s=10.0,
        max_attempts=3,
    )

    result = policy.call(func, on_metric=noisy_metric, on_log=noisy_log)
    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.parametrize("limit, expected_calls", [(0, 1), (1, 2), (2, 3)])
def test_per_class_max_attempts_limits_retries(
    monkeypatch: pytest.MonkeyPatch, limit: int, expected_calls: int
) -> None:
    """
    per_class_max_attempts limits retries for a specific error class.
    """

    class RateLimitError(Exception):
        pass

    calls = {"n": 0}

    def func() -> None:
        calls["n"] += 1
        raise RateLimitError("429")

    metric_hook, events = _collect_metrics()

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.RATE_LIMIT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=instant_retries,
        per_class_max_attempts={ErrorClass.RATE_LIMIT: limit},
        max_attempts=10,
    )

    with pytest.raises(RateLimitError) as excinfo:
        policy.call(func, on_metric=metric_hook)

    _assert_tb_has_frame(excinfo.value, func.__name__)

    assert calls["n"] == expected_calls
    assert events[-1][0] == "max_attempts_exceeded"
    assert events[-1][3]["class"] == ErrorClass.RATE_LIMIT.name
    assert events[-1][3]["stop_reason"] == StopReason.MAX_ATTEMPTS_PER_CLASS.value


def test_retry_policy_from_config_creates_equivalent_policy() -> None:
    """
    from_config should pass through deadlines, attempts, per-class limits, and strategies.
    """

    cfg = RetryConfig(
        deadline_s=12.0,
        max_attempts=4,
        max_unknown_attempts=1,
        per_class_max_attempts={ErrorClass.RATE_LIMIT: 2},
        default_strategy=instant_retries,
        class_strategies={ErrorClass.CONCURRENCY: instant_retries},
        result_classifier=lambda result: None,
    )

    policy = RetryPolicy.from_config(cfg, classifier=lambda e: ErrorClass.UNKNOWN)

    assert policy.deadline.total_seconds() == cfg.deadline_s
    assert policy.max_attempts == cfg.max_attempts
    assert policy.max_unknown_attempts == cfg.max_unknown_attempts
    assert policy.per_class_max_attempts[ErrorClass.RATE_LIMIT] == 2
    assert policy.result_classifier is cfg.result_classifier
    # Strategy lookup should invoke the configured strategies.
    assert policy._default_strategy is not None
    assert (
        policy._default_strategy(
            BackoffContext(
                attempt=1,
                classification=Classification(klass=ErrorClass.UNKNOWN),
                prev_sleep_s=None,
                remaining_s=10.0,
                cause="exception",
            )
        )
        == 0.0
    )
    assert (
        policy._strategies[ErrorClass.CONCURRENCY](
            BackoffContext(
                attempt=1,
                classification=Classification(klass=ErrorClass.CONCURRENCY),
                prev_sleep_s=None,
                remaining_s=10.0,
                cause="exception",
            )
        )
        == 0.0
    )


def test_retry_from_config() -> None:
    cfg = RetryConfig(
        deadline_s=5.0,
        max_attempts=2,
        max_unknown_attempts=1,
        default_strategy=instant_retries,
    )

    retry = Retry.from_config(cfg, classifier=lambda e: ErrorClass.UNKNOWN)

    assert retry.deadline.total_seconds() == cfg.deadline_s
    assert retry.max_attempts == cfg.max_attempts


# ---------------------------------------------------------------------------
# Strategy registry behavior
# ---------------------------------------------------------------------------


def test_per_class_strategy_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verify that per-class strategies override the default strategy.
    """
    calls: dict[str, int] = {"default": 0, "rate_limit": 0}

    def default_strategy(attempt: int, klass: ErrorClass, prev_sleep: float | None) -> float:
        calls["default"] += 1
        return 0.0

    def rate_limit_strategy(attempt: int, klass: ErrorClass, prev_sleep: float | None) -> float:
        calls["rate_limit"] += 1
        return 0.0

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    # Classifier that always returns RATE_LIMIT
    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.RATE_LIMIT

    # Func that fails twice with RateLimitError then succeeds
    attempt_counter = {"n": 0}

    def func() -> str:
        attempt_counter["n"] += 1
        if attempt_counter["n"] < 3:
            raise RateLimitError("429")
        return "ok"

    policy = RetryPolicy(
        classifier=classifier,
        strategy=default_strategy,
        strategies={ErrorClass.RATE_LIMIT: rate_limit_strategy},
        deadline_s=30.0,
        max_attempts=5,
    )

    result = policy.call(func)
    assert result == "ok"

    # We should have used the per-class strategy for RATE_LIMIT, not the default
    assert calls["rate_limit"] == 2  # two retries
    assert calls["default"] == 0


def test_strategy_required() -> None:
    """
    RetryPolicy must be constructed with at least one strategy source:
    either a default strategy or a strategies mapping.
    """
    with pytest.raises(ValueError):
        RetryPolicy(
            classifier=lambda e: ErrorClass.TRANSIENT,
            strategy=None,
            strategies=None,
        )


# ---------------------------------------------------------------------------
# Unknown error behavior
# ---------------------------------------------------------------------------


def test_unknown_errors_respect_max_unknown_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    UNKNOWN error class should respect max_unknown_attempts,
    even if max_attempts is larger.
    """

    class WeirdError(Exception):
        pass

    call_count = {"n": 0}

    def func() -> None:
        call_count["n"] += 1
        raise WeirdError("???")

    metric_hook, events = _collect_metrics()

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.UNKNOWN

    policy = RetryPolicy(
        classifier=classifier,
        strategy=instant_retries,
        deadline_s=30.0,
        max_attempts=10,
        max_unknown_attempts=2,
    )

    with pytest.raises(WeirdError) as excinfo:
        policy.call(func, on_metric=metric_hook)

    _assert_tb_has_frame(excinfo.value, func.__name__)

    # Should only attempt 3 times total:
    #   1st unknown  -> retry
    #   2nd unknown  -> retry
    #   3rd unknown  -> exceeds max_unknown_attempts -> raise
    assert call_count["n"] == 3

    events_by_name = [e[0] for e in events]
    assert "max_unknown_attempts_exceeded" in events_by_name
    unknown_event = next(e for e in events if e[0] == "max_unknown_attempts_exceeded")
    assert unknown_event[3]["stop_reason"] == StopReason.MAX_UNKNOWN_ATTEMPTS.value


# ---------------------------------------------------------------------------
# Deadline behavior
# ---------------------------------------------------------------------------


def test_deadline_exceeded_stops_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    When the deadline is exceeded, retries should stop and the last
    exception should be raised. We fake time to avoid real waiting.
    """

    class SlowError(Exception):
        pass

    fake_time = _FakeTime()

    # Monkeypatch monotonic and sleep in the retry/state modules.
    monkeypatch.setattr(_state_mod.time, "monotonic", fake_time.monotonic)
    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: fake_time.advance(s))

    call_count = {"n": 0}

    def func() -> None:
        call_count["n"] += 1
        raise SlowError("still failing")

    metric_hook, events = _collect_metrics()

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    # deadline_s is very small to keep logic simple
    policy = RetryPolicy(
        classifier=classifier,
        strategy=lambda attempt, klass, prev: 1.0,  # always sleep 1 second
        deadline_s=2.0,
        max_attempts=10,
    )

    with pytest.raises(SlowError) as excinfo:
        policy.call(func, on_metric=metric_hook)

    _assert_tb_has_frame(excinfo.value, func.__name__)

    # We should see at least one retry but stop once > 2 seconds passed.
    # Exact count depends on start, but we can check deadline_exceeded metric.
    deadline_event = next(e for e in events if e[0] == "deadline_exceeded")
    assert deadline_event[3]["stop_reason"] == StopReason.DEADLINE_EXCEEDED.value


def test_deadline_sleep_is_capped_and_rechecked(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    A retry scheduled longer than the remaining deadline should be capped,
    and we should re-check the deadline after sleeping before starting a new
    attempt.
    """

    class SlowError(Exception):
        pass

    fake_time = _FakeTime()

    # Patch monotonic in state and track sleeps in retry.
    monkeypatch.setattr(_state_mod.time, "monotonic", fake_time.monotonic)
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        # Add a small overhead to ensure we cross the deadline boundary.
        fake_time.advance(seconds + 0.01)

    monkeypatch.setattr(_retry_mod.time, "sleep", fake_sleep)

    calls = {"n": 0}

    def func() -> None:
        calls["n"] += 1
        fake_time.advance(0.2)  # simulate some work before failure
        raise SlowError("still failing")

    metric_hook, events = _collect_metrics()

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    def strategy(ctx: BackoffContext) -> float:
        assert ctx.remaining_s == pytest.approx(0.8)
        return 10.0  # would sleep long without capping

    policy = RetryPolicy(
        classifier=classifier,
        strategy=strategy,
        deadline_s=1.0,
        max_attempts=5,
    )

    with pytest.raises(SlowError):
        policy.call(func, on_metric=metric_hook)

    # Only the first attempt should run; the deadline expires during the capped sleep.
    assert calls["n"] == 1
    assert sleep_calls and sleep_calls[0] == pytest.approx(0.8)

    # Retry event should reflect the capped sleep duration, and deadline_exceeded should fire.
    retry_event = next(e for e in events if e[0] == "retry")
    assert retry_event[2] == pytest.approx(0.8)
    deadline_event = next(e for e in events if e[0] == "deadline_exceeded")
    assert deadline_event[3]["stop_reason"] == StopReason.DEADLINE_EXCEEDED.value


# ---------------------------------------------------------------------------
# Integration-ish test with default_classifier
# ---------------------------------------------------------------------------


def test_default_classifier_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Light integration check for default_classifier + RetryPolicy.
    We simulate an HTTP-like error object with status=429 and ensure
    it's treated as RATE_LIMIT.
    """

    class Http429Error(Exception):
        def __init__(self, status: int) -> None:
            self.status = status

    calls = {"n": 0}

    def func() -> None:
        calls["n"] += 1
        raise Http429Error(429)

    metric_hook, events = _collect_metrics()

    # Avoid real sleeping
    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    # Wrap a classifier spy around default_classifier
    seen_classes: list[ErrorClass] = []

    def classifier(err: BaseException) -> ErrorClass:
        klass = default_classifier(err)
        seen_classes.append(klass)
        return klass

    policy = RetryPolicy(
        classifier=classifier,
        strategy=instant_retries,
        deadline_s=5.0,
        max_attempts=3,
    )

    with pytest.raises(Http429Error):
        policy.call(func, on_metric=metric_hook)


# ---------------------------------------------------------------------------
# Result-based retries
# ---------------------------------------------------------------------------


def test_result_classifier_retries_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def func() -> str:
        calls["n"] += 1
        return "retry" if calls["n"] == 1 else "ok"

    def result_classifier(result: str) -> ErrorClass | None:
        return ErrorClass.TRANSIENT if result == "retry" else None

    def strategy(ctx: BackoffContext) -> float:
        assert ctx.cause == "result"
        return 0.0

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    policy = RetryPolicy(
        classifier=default_classifier,
        result_classifier=result_classifier,
        strategy=strategy,
        deadline_s=10.0,
        max_attempts=3,
    )

    assert policy.call(func) == "ok"
    assert calls["n"] == 2


def test_result_classifier_exhausts_with_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def func() -> str:
        return "bad"

    def result_classifier(result: str) -> ErrorClass | None:
        return ErrorClass.TRANSIENT

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    policy = RetryPolicy(
        classifier=default_classifier,
        result_classifier=result_classifier,
        strategy=instant_retries,
        deadline_s=10.0,
        max_attempts=2,
    )

    with pytest.raises(RetryExhaustedError) as excinfo:
        policy.call(func)

    err = excinfo.value
    assert err.stop_reason == StopReason.MAX_ATTEMPTS_GLOBAL
    assert err.attempts == 2
    assert err.last_class is ErrorClass.TRANSIENT
    assert err.last_exception is None
    assert err.last_result == "bad"


def test_result_classifier_non_retryable_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    def func() -> str:
        return "bad"

    def result_classifier(result: str) -> ErrorClass | None:
        return ErrorClass.PERMANENT

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    policy = RetryPolicy(
        classifier=default_classifier,
        result_classifier=result_classifier,
        strategy=instant_retries,
        deadline_s=10.0,
        max_attempts=3,
    )

    with pytest.raises(RetryExhaustedError) as excinfo:
        policy.call(func)

    err = excinfo.value
    assert err.stop_reason == StopReason.NON_RETRYABLE_CLASS
    assert err.attempts == 1
    assert err.last_class is ErrorClass.PERMANENT


def test_result_classifier_respects_max_unknown_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def func() -> str:
        return "bad"

    def result_classifier(result: str) -> ErrorClass | None:
        return ErrorClass.UNKNOWN

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    policy = RetryPolicy(
        classifier=default_classifier,
        result_classifier=result_classifier,
        strategy=instant_retries,
        deadline_s=10.0,
        max_attempts=3,
        max_unknown_attempts=0,
    )

    with pytest.raises(RetryExhaustedError) as excinfo:
        policy.call(func)

    err = excinfo.value
    assert err.stop_reason == StopReason.MAX_UNKNOWN_ATTEMPTS
    assert err.attempts == 1
    assert err.last_class is ErrorClass.UNKNOWN


def test_result_classifier_respects_per_class_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    def func() -> str:
        return "bad"

    def result_classifier(result: str) -> ErrorClass | None:
        return ErrorClass.RATE_LIMIT

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    policy = RetryPolicy(
        classifier=default_classifier,
        result_classifier=result_classifier,
        strategy=instant_retries,
        deadline_s=10.0,
        max_attempts=3,
        per_class_max_attempts={ErrorClass.RATE_LIMIT: 0},
    )

    with pytest.raises(RetryExhaustedError) as excinfo:
        policy.call(func)

    err = excinfo.value
    assert err.stop_reason == StopReason.MAX_ATTEMPTS_PER_CLASS
    assert err.attempts == 1
    assert err.last_class is ErrorClass.RATE_LIMIT


def test_result_classifier_mixed_failures_prefer_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FlakyError(Exception):
        pass

    calls = {"n": 0}

    def func() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise FlakyError("boom")
        return "bad"

    def classifier(exc: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    def result_classifier(result: str) -> ErrorClass | None:
        return ErrorClass.PERMANENT

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    policy = RetryPolicy(
        classifier=classifier,
        result_classifier=result_classifier,
        strategy=instant_retries,
        deadline_s=10.0,
        max_attempts=3,
    )

    with pytest.raises(RetryExhaustedError) as excinfo:
        policy.call(func)

    err = excinfo.value
    assert err.stop_reason == StopReason.NON_RETRYABLE_CLASS
    assert err.attempts == 2
    assert err.last_class is ErrorClass.PERMANENT
    assert err.last_exception is None
    assert err.last_result == "bad"


def test_result_classifier_emits_cause_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    def func() -> str:
        return "bad"

    def result_classifier(result: str) -> ErrorClass | None:
        return ErrorClass.TRANSIENT

    metric_hook, events = _collect_metrics()

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    policy = RetryPolicy(
        classifier=default_classifier,
        result_classifier=result_classifier,
        strategy=instant_retries,
        deadline_s=10.0,
        max_attempts=2,
    )

    with pytest.raises(RetryExhaustedError):
        policy.call(func, on_metric=metric_hook)

    retry_event = next(event for event in events if event[0] == "retry")
    assert retry_event[3]["cause"] == "result"
    assert "err" not in retry_event[3]


def test_policy_matches_retry_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    def classifier(exc: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    def make_flaky() -> tuple[object, dict[str, int]]:
        calls = {"n": 0}

        def func() -> str:
            calls["n"] += 1
            if calls["n"] < 2:
                raise ValueError("boom")
            return "ok"

        return func, calls

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    metric_hook_a, events_a = _collect_metrics()
    func_a, calls_a = make_flaky()
    policy_a = RetryPolicy(
        classifier=classifier,
        strategy=instant_retries,
        deadline_s=10.0,
        max_attempts=3,
    )
    result_a = policy_a.call(func_a, on_metric=metric_hook_a)

    metric_hook_b, events_b = _collect_metrics()
    func_b, calls_b = make_flaky()
    policy_b = Policy(
        retry=Retry(
            classifier=classifier,
            strategy=instant_retries,
            deadline_s=10.0,
            max_attempts=3,
        )
    )
    result_b = policy_b.call(func_b, on_metric=metric_hook_b)

    assert result_a == result_b == "ok"
    assert calls_a["n"] == calls_b["n"] == 2
    assert events_a == events_b


def test_policy_breaker_counts_once_per_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def func() -> None:
        calls["n"] += 1
        raise RateLimitError("429")

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    breaker = CircuitBreaker(
        failure_threshold=2,
        window_s=60.0,
        recovery_timeout_s=30.0,
        trip_on={ErrorClass.TRANSIENT},
    )

    policy = Policy(
        retry=Retry(
            classifier=lambda exc: ErrorClass.TRANSIENT,
            strategy=instant_retries,
            max_attempts=2,
        ),
        circuit_breaker=breaker,
    )

    events: list[str] = []

    def metric(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        if event.startswith("circuit_"):
            events.append(event)

    with pytest.raises(RateLimitError):
        policy.call(func, on_metric=metric)

    assert breaker.state is CircuitState.CLOSED

    with pytest.raises(RateLimitError):
        policy.call(func, on_metric=metric)

    assert breaker.state is CircuitState.OPEN
    assert events.count("circuit_opened") == 1


def test_policy_breaker_rejects_when_open(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def func() -> None:
        calls["n"] += 1
        raise RateLimitError("429")

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=60.0,
        recovery_timeout_s=30.0,
        trip_on={ErrorClass.TRANSIENT},
    )

    policy = Policy(
        retry=Retry(
            classifier=lambda exc: ErrorClass.TRANSIENT,
            strategy=instant_retries,
            max_attempts=1,
        ),
        circuit_breaker=breaker,
    )

    events: list[str] = []

    def metric(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        if event.startswith("circuit_"):
            events.append(event)

    with pytest.raises(RateLimitError):
        policy.call(func, on_metric=metric)

    assert calls["n"] == 1
    assert breaker.state is CircuitState.OPEN

    with pytest.raises(CircuitOpenError):
        policy.call(func, on_metric=metric)

    assert calls["n"] == 1
    assert "circuit_opened" in events
    assert "circuit_rejected" in events


def test_policy_breaker_emits_transition_events(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time = _FakeTime()

    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=2.0,
        trip_on={ErrorClass.TRANSIENT},
        clock=fake_time.monotonic,
    )

    policy = Policy(
        retry=Retry(
            classifier=lambda exc: ErrorClass.TRANSIENT,
            strategy=instant_retries,
            max_attempts=1,
        ),
        circuit_breaker=breaker,
    )

    events: list[tuple[str, dict[str, Any]]] = []

    def metric(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
        if event.startswith("circuit_"):
            events.append((event, tags))

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    def fail() -> None:
        raise RateLimitError("429")

    with pytest.raises(RateLimitError):
        policy.call(fail, on_metric=metric, operation="op")

    fake_time.advance(2.1)

    def succeed() -> str:
        return "ok"

    assert policy.call(succeed, on_metric=metric, operation="op") == "ok"

    names = [event for event, _ in events]
    assert "circuit_opened" in names
    assert "circuit_half_open" in names
    assert "circuit_closed" in names

    opened_tags = next(tags for event, tags in events if event == "circuit_opened")
    assert opened_tags["class"] == ErrorClass.TRANSIENT.name
    assert opened_tags["operation"] == "op"
    assert opened_tags["state"] == "open"


def test_policy_breaker_uses_default_classifier_without_retry() -> None:
    class WeirdError(Exception):
        pass

    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.UNKNOWN},
    )

    policy = Policy(circuit_breaker=breaker)

    def fail() -> None:
        raise WeirdError("boom")

    with pytest.raises(WeirdError):
        policy.call(fail)

    assert breaker.state is CircuitState.OPEN


def test_policy_breaker_records_result_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.TRANSIENT},
    )

    policy = Policy(
        retry=Retry(
            classifier=default_classifier,
            result_classifier=lambda result: ErrorClass.TRANSIENT,
            strategy=instant_retries,
            max_attempts=1,
        ),
        circuit_breaker=breaker,
    )

    monkeypatch.setattr(_retry_mod.time, "sleep", lambda s: None)

    with pytest.raises(RetryExhaustedError):
        policy.call(lambda: "bad")

    assert breaker.state is CircuitState.OPEN


def test_policy_breaker_ignores_circuit_open_error() -> None:
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.TRANSIENT},
    )

    policy = Policy(circuit_breaker=breaker)

    def fail() -> None:
        raise CircuitOpenError("open")

    with pytest.raises(CircuitOpenError):
        policy.call(fail)

    assert breaker.state is CircuitState.CLOSED


def test_policy_execute_no_retry_failure_emits_breaker_event() -> None:
    class WeirdError(Exception):
        pass

    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.UNKNOWN},
    )

    policy = Policy(circuit_breaker=breaker)
    metric_hook, events = _collect_metrics()

    def fail() -> None:
        raise WeirdError("boom")

    outcome = policy.execute(fail, on_metric=metric_hook, operation="op")

    assert outcome.ok is False
    assert outcome.attempts == 1
    assert isinstance(outcome.last_exception, WeirdError)
    assert outcome.last_class is ErrorClass.UNKNOWN
    assert outcome.cause == "exception"
    assert breaker.state is CircuitState.OPEN

    opened_tags = next(tags for event, _, _, tags in events if event == "circuit_opened")
    assert opened_tags["state"] == CircuitState.OPEN.value
    assert opened_tags["operation"] == "op"


def test_policy_execute_breaker_rejected_returns_outcome() -> None:
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=30.0,
        trip_on={ErrorClass.UNKNOWN},
    )
    breaker.record_failure(ErrorClass.UNKNOWN)

    policy = Policy(circuit_breaker=breaker)
    metric_hook, events = _collect_metrics()

    outcome = policy.execute(lambda: "ok", on_metric=metric_hook, operation="op")

    assert outcome.ok is False
    assert outcome.attempts == 0
    assert isinstance(outcome.last_exception, CircuitOpenError)
    assert breaker.state is CircuitState.OPEN

    rejected_tags = next(tags for event, _, _, tags in events if event == "circuit_rejected")
    assert rejected_tags["state"] == CircuitState.OPEN.value
    assert rejected_tags["operation"] == "op"


def test_policy_execute_with_retry_aborted_records_cancel() -> None:
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
        trip_on={ErrorClass.TRANSIENT},
    )

    called = {"n": 0}
    original = breaker.record_cancel

    def record_cancel() -> None:
        called["n"] += 1
        original()

    breaker.record_cancel = record_cancel  # type: ignore[assignment]

    policy = Policy(
        retry=Retry(
            classifier=default_classifier,
            strategy=instant_retries,
            max_attempts=3,
        ),
        circuit_breaker=breaker,
    )

    outcome = policy.execute(lambda: "ok", abort_if=lambda: True)

    assert outcome.stop_reason is StopReason.ABORTED
    assert outcome.attempts == 0
    assert called["n"] == 1


def test_policy_execute_breaker_half_open_success_emits_events() -> None:
    fake_time = _FakeTime()
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=1.0,
        trip_on={ErrorClass.UNKNOWN},
        clock=fake_time.monotonic,
    )
    breaker.record_failure(ErrorClass.UNKNOWN)
    fake_time.advance(1.1)

    policy = Policy(circuit_breaker=breaker)
    metric_hook, events = _collect_metrics()
    log_events: list[tuple[str, dict[str, Any]]] = []

    def log_hook(event: str, fields: dict[str, Any]) -> None:
        log_events.append((event, fields))

    outcome = policy.execute(lambda: "ok", on_metric=metric_hook, on_log=log_hook)

    assert outcome.ok is True
    event_names = [event for event, _, _, _ in events]
    assert "circuit_half_open" in event_names
    assert "circuit_closed" in event_names
    assert any(event == "circuit_half_open" for event, _ in log_events)


def test_policy_execute_no_retry_abort_if_returns_outcome() -> None:
    policy = Policy()

    outcome = policy.execute(lambda: "ok", abort_if=lambda: True)

    assert outcome.stop_reason is StopReason.ABORTED
    assert outcome.attempts == 0


def test_policy_execute_breaker_event_hooks_swallow_errors() -> None:
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=30.0,
        trip_on={ErrorClass.UNKNOWN},
    )
    breaker.record_failure(ErrorClass.UNKNOWN)

    policy = Policy(circuit_breaker=breaker)

    def metric_hook(_: str, __: int, ___: float, ____: dict[str, Any]) -> None:
        raise RuntimeError("metric fail")

    def log_hook(_: str, __: dict[str, Any]) -> None:
        raise RuntimeError("log fail")

    outcome = policy.execute(lambda: "ok", on_metric=metric_hook, on_log=log_hook)

    assert outcome.ok is False
    assert isinstance(outcome.last_exception, CircuitOpenError)


def test_policy_call_no_retry_abort_if_raises() -> None:
    policy = Policy()

    with pytest.raises(AbortRetryError):
        policy.call(lambda: "ok", abort_if=lambda: True)


def test_policy_call_no_retry_abort_if_records_cancel() -> None:
    breaker = CircuitBreaker(
        failure_threshold=1,
        window_s=10.0,
        recovery_timeout_s=5.0,
    )
    called = {"n": 0}
    original = breaker.record_cancel

    def record_cancel() -> None:
        called["n"] += 1
        original()

    breaker.record_cancel = record_cancel  # type: ignore[assignment]

    policy = Policy(circuit_breaker=breaker)

    with pytest.raises(AbortRetryError):
        policy.call(lambda: "ok", abort_if=lambda: True)

    assert called["n"] == 1
