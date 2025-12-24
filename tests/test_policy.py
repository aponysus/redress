# tests/test_policy.py


from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from redress.classify import default_classifier
from redress.config import RetryConfig
from redress.errors import (
    ErrorClass,
    PermanentError,
    RateLimitError,
)
from redress.policy import MetricHook, RetryPolicy
from redress.strategies import decorrelated_jitter


class _FakeTime:
    """
    Simple fake clock to control time in deadline tests.

    We mimic datetime.now(UTC) by exposing now() and advance() helpers.
    """

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


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


def _no_sleep_strategy(_: int, __: ErrorClass, ___: float | None) -> float:
    """
    Strategy that always returns 0 seconds sleep (for fast tests).
    """
    return 0.0


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
    monkeypatch.setattr("redress.policy.time.sleep", lambda s: None)

    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=1.0),
        deadline_s=30.0,
        max_attempts=5,
    )

    with pytest.raises(PermanentError):
        policy.call(func, on_metric=metric_hook)

    # Only one attempt
    assert call_count["n"] == 1

    # Metrics: single permanent_fail, no 'retry'
    assert len(events) == 1
    event, attempt, sleep_s, tags = events[0]
    assert event == "permanent_fail"
    assert attempt == 1
    assert sleep_s == 0.0
    assert tags["err"] == "PermanentError"
    assert tags["class"] == ErrorClass.PERMANENT.name


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

    monkeypatch.setattr("redress.policy.time.sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.AUTH

    policy = RetryPolicy(
        classifier=classifier,
        strategy=_no_sleep_strategy,
        deadline_s=30.0,
        max_attempts=5,
    )

    with pytest.raises(AuthError):
        policy.call(func, on_metric=metric_hook)

    assert call_count["n"] == 1
    event, attempt, sleep_s, tags = events[0]
    assert event == "permanent_fail"
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

    monkeypatch.setattr("redress.policy.time.sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.PERMISSION

    policy = RetryPolicy(
        classifier=classifier,
        strategy=_no_sleep_strategy,
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

    monkeypatch.setattr("redress.policy.time.sleep", lambda s: None)

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

    monkeypatch.setattr("redress.policy.time.sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=_no_sleep_strategy,
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

    monkeypatch.setattr("redress.policy.time.sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=_no_sleep_strategy,
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

    monkeypatch.setattr("redress.policy.time.sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=_no_sleep_strategy,
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

    monkeypatch.setattr("redress.policy.time.sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=_no_sleep_strategy,
        deadline_s=10.0,
        max_attempts=3,
    )

    result = policy.call(func, on_metric=noisy_metric, on_log=noisy_log)
    assert result == "ok"
    assert calls["n"] == 2


def test_per_class_max_attempts_limits_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    per_class_max_attempts should cap retries for a specific error class.
    """

    class RateLimitError(Exception):
        pass

    calls = {"n": 0}

    def func() -> None:
        calls["n"] += 1
        raise RateLimitError("429")

    metric_hook, events = _collect_metrics()

    monkeypatch.setattr("redress.policy.time.sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.RATE_LIMIT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=_no_sleep_strategy,
        per_class_max_attempts={ErrorClass.RATE_LIMIT: 2},
        max_attempts=10,
    )

    with pytest.raises(RateLimitError):
        policy.call(func, on_metric=metric_hook)

    # initial + 2 retries, then cap hit
    assert calls["n"] == 3
    assert events[-1][0] == "max_attempts_exceeded"
    assert events[-1][3]["class"] == ErrorClass.RATE_LIMIT.name


def test_retry_policy_from_config_creates_equivalent_policy() -> None:
    """
    from_config should pass through deadlines, attempts, per-class limits, and strategies.
    """

    cfg = RetryConfig(
        deadline_s=12.0,
        max_attempts=4,
        max_unknown_attempts=1,
        per_class_max_attempts={ErrorClass.RATE_LIMIT: 2},
        default_strategy=_no_sleep_strategy,
        class_strategies={ErrorClass.CONCURRENCY: _no_sleep_strategy},
    )

    policy = RetryPolicy.from_config(cfg, classifier=lambda e: ErrorClass.UNKNOWN)

    assert policy.deadline.total_seconds() == cfg.deadline_s
    assert policy.max_attempts == cfg.max_attempts
    assert policy.max_unknown_attempts == cfg.max_unknown_attempts
    assert policy.per_class_max_attempts[ErrorClass.RATE_LIMIT] == 2
    # Strategy lookup should match what we provided
    assert policy._default_strategy is _no_sleep_strategy
    assert policy._strategies[ErrorClass.CONCURRENCY] is _no_sleep_strategy


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

    monkeypatch.setattr("redress.policy.time.sleep", lambda s: None)

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

    monkeypatch.setattr("redress.policy.time.sleep", lambda s: None)

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.UNKNOWN

    policy = RetryPolicy(
        classifier=classifier,
        strategy=_no_sleep_strategy,
        deadline_s=30.0,
        max_attempts=10,
        max_unknown_attempts=2,
    )

    with pytest.raises(WeirdError):
        policy.call(func, on_metric=metric_hook)

    # Should only attempt 3 times total:
    #   1st unknown  -> retry
    #   2nd unknown  -> retry
    #   3rd unknown  -> exceeds max_unknown_attempts -> raise
    assert call_count["n"] == 3

    events_by_name = [e[0] for e in events]
    assert "max_unknown_attempts_exceeded" in events_by_name


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

    # Monkeypatch both datetime.now(UTC) usage inside redress.policy and sleep
    def fake_now(_: Any = None) -> datetime:
        return fake_time.now()

    monkeypatch.setattr(
        "redress.policy.datetime", type("DT", (), {"now": staticmethod(fake_now), "UTC": UTC})
    )
    monkeypatch.setattr("redress.policy.time.sleep", lambda s: fake_time.advance(s))

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

    with pytest.raises(SlowError):
        policy.call(func, on_metric=metric_hook)

    # We should see at least one retry but stop once > 2 seconds passed.
    # Exact count depends on start, but we can check deadline_exceeded metric.
    assert "deadline_exceeded" in [e[0] for e in events]


def test_deadline_sleep_is_capped_and_rechecked(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    A retry scheduled longer than the remaining deadline should be capped,
    and we should re-check the deadline after sleeping before starting a new
    attempt.
    """

    class SlowError(Exception):
        pass

    fake_time = _FakeTime()

    def fake_now(_: Any = None) -> datetime:
        return fake_time.now()

    # Patch datetime.now(UTC) inside redress.policy and track sleeps.
    monkeypatch.setattr(
        "redress.policy.datetime", type("DT", (), {"now": staticmethod(fake_now), "UTC": UTC})
    )
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        # Add a small overhead to ensure we cross the deadline boundary.
        fake_time.advance(seconds + 0.01)

    monkeypatch.setattr("redress.policy.time.sleep", fake_sleep)

    calls = {"n": 0}

    def func() -> None:
        calls["n"] += 1
        fake_time.advance(0.2)  # simulate some work before failure
        raise SlowError("still failing")

    metric_hook, events = _collect_metrics()

    def classifier(err: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy = RetryPolicy(
        classifier=classifier,
        strategy=lambda attempt, klass, prev: 10.0,  # would sleep long without capping
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
    assert "deadline_exceeded" in [e[0] for e in events]


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
    monkeypatch.setattr("redress.policy.time.sleep", lambda s: None)

    # Wrap a classifier spy around default_classifier
    seen_classes: list[ErrorClass] = []

    def classifier(err: BaseException) -> ErrorClass:
        klass = default_classifier(err)
        seen_classes.append(klass)
        return klass

    policy = RetryPolicy(
        classifier=classifier,
        strategy=_no_sleep_strategy,
        deadline_s=5.0,
        max_attempts=3,
    )

    with pytest.raises(Http429Error):
        policy.call(func, on_metric=metric_hook)

    # default_classifier should classify as RATE_LIMIT
    assert seen_classes and all(k is ErrorClass.RATE_LIMIT for k in seen_classes)

    # We should have retried until max_attempts exceeded
    assert calls["n"] == 3
    assert events[-1][0] == "max_attempts_exceeded"
