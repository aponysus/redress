# tests/test_celery_contrib.py

from typing import Any

from redress import RetryPolicy, SleepDecision
from redress.contrib import celery as celery_contrib
from redress.contrib.celery import (
    default_operation,
    default_retry_kwargs,
    defer_sleep,
    execute_task_with_retry,
)
from redress.errors import ErrorClass, RetryExhaustedError, StopReason
from redress.policy.types import RetryOutcome


class _FakeTask:
    def __init__(self, name: str | None = "tasks.example") -> None:
        self.name = name
        self.retry_calls: list[dict[str, Any]] = []

    def retry(self, **kwargs: Any) -> str:
        self.retry_calls.append(kwargs)
        return "retried"


class _AnonymousTask:
    name = None

    def retry(self, **kwargs: Any) -> str:
        return "retried"


class _FakePolicy:
    def __init__(self, outcome: RetryOutcome[Any]) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    def execute(self, func, **kwargs):
        self.calls.append(kwargs)
        return self.outcome


def _success_outcome(value: Any) -> RetryOutcome[Any]:
    return RetryOutcome(
        ok=True,
        value=value,
        stop_reason=None,
        attempts=1,
        last_class=None,
        last_exception=None,
        last_result=None,
        cause=None,
        elapsed_s=0.0,
    )


def _scheduled_outcome(
    *,
    next_sleep_s: float | None = 2.5,
    last_exception: BaseException | None = None,
) -> RetryOutcome[Any]:
    return RetryOutcome(
        ok=False,
        value=None,
        stop_reason=StopReason.SCHEDULED,
        attempts=2,
        last_class=ErrorClass.TRANSIENT,
        last_exception=last_exception,
        last_result=None,
        cause="exception" if last_exception is not None else None,
        elapsed_s=0.2,
        next_sleep_s=next_sleep_s,
    )


def _failed_result_outcome() -> RetryOutcome[Any]:
    return RetryOutcome(
        ok=False,
        value=None,
        stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
        attempts=3,
        last_class=ErrorClass.SERVER_ERROR,
        last_exception=None,
        last_result={"status": 503},
        cause="result",
        elapsed_s=1.0,
    )


def test_defer_sleep_returns_defer() -> None:
    assert defer_sleep(None, 1.5) is SleepDecision.DEFER


def test_default_operation_prefers_task_name() -> None:
    assert default_operation(_FakeTask("tasks.sync_user")) == "tasks.sync_user"


def test_default_operation_falls_back_to_task_type_name() -> None:
    value = default_operation(_AnonymousTask())
    assert value.endswith("._AnonymousTask") or value == "_AnonymousTask"


def test_default_retry_kwargs_from_scheduled_outcome() -> None:
    outcome = _scheduled_outcome(next_sleep_s=3.0, last_exception=RuntimeError("boom"))
    kwargs = default_retry_kwargs(outcome, _FakeTask())
    assert kwargs["countdown"] == 3.0
    assert isinstance(kwargs["exc"], RuntimeError)


def test_default_retry_kwargs_omits_missing_values() -> None:
    assert default_retry_kwargs(_scheduled_outcome(next_sleep_s=None), _FakeTask()) == {}


def test_execute_task_with_retry_returns_success_value() -> None:
    policy = _FakePolicy(_success_outcome("ok"))
    task = _FakeTask()
    result = execute_task_with_retry(task, policy, lambda: "ignored")
    assert result == "ok"
    assert len(policy.calls) == 1
    assert policy.calls[0]["operation"] == "tasks.example"
    assert policy.calls[0]["sleep"] is defer_sleep


def test_execute_task_with_retry_accepts_execute_kwargs_provider() -> None:
    policy = _FakePolicy(_success_outcome("ok"))
    task = _FakeTask("tasks.override")
    custom_sleep = object()

    execute_task_with_retry(
        task,
        policy,
        lambda: "ignored",
        operation=lambda t: f"op:{t.name}",
        execute_kwargs=lambda _task: {
            "operation": "custom-op",
            "sleep": custom_sleep,
            "tags": {"x": 1},
        },
    )

    assert policy.calls == [{"operation": "custom-op", "sleep": custom_sleep, "tags": {"x": 1}}]


def test_execute_task_with_retry_scheduled_calls_task_retry() -> None:
    def func() -> str:
        raise RuntimeError("boom")

    policy = RetryPolicy(
        classifier=lambda _: ErrorClass.TRANSIENT,
        strategy=lambda _ctx: 1.5,
        deadline_s=5.0,
        max_attempts=3,
    )
    task = _FakeTask("tasks.scheduled")

    result = execute_task_with_retry(task, policy, func)
    assert result == "retried"
    assert len(task.retry_calls) == 1
    assert task.retry_calls[0]["countdown"] == 1.5
    assert isinstance(task.retry_calls[0]["exc"], RuntimeError)


def test_execute_task_with_retry_retry_kwargs_override_defaults() -> None:
    policy = _FakePolicy(_scheduled_outcome(next_sleep_s=2.0, last_exception=RuntimeError("boom")))
    task = _FakeTask()

    result = execute_task_with_retry(
        task,
        policy,
        lambda: "ignored",
        retry_kwargs=lambda _outcome, _task: {"countdown": 9.0, "max_retries": 7},
    )

    assert result == "retried"
    assert task.retry_calls == [
        {"countdown": 9.0, "exc": policy.outcome.last_exception, "max_retries": 7}
    ]


def test_execute_task_with_retry_reraises_last_exception() -> None:
    exc = ValueError("bad")
    policy = _FakePolicy(_scheduled_outcome(next_sleep_s=1.0, last_exception=exc))
    task = _FakeTask()

    policy.outcome = RetryOutcome(
        ok=False,
        value=None,
        stop_reason=StopReason.NON_RETRYABLE_CLASS,
        attempts=1,
        last_class=ErrorClass.PERMANENT,
        last_exception=exc,
        last_result=None,
        cause="exception",
        elapsed_s=0.0,
    )

    try:
        execute_task_with_retry(task, policy, lambda: "ignored")
    except ValueError as raised:
        assert raised is exc
    else:
        raise AssertionError("expected ValueError")


def test_execute_task_with_retry_raises_retry_exhausted_for_result_failures() -> None:
    policy = _FakePolicy(_failed_result_outcome())
    task = _FakeTask()

    try:
        execute_task_with_retry(task, policy, lambda: "ignored")
    except RetryExhaustedError as exc:
        assert exc.stop_reason is StopReason.MAX_ATTEMPTS_GLOBAL
        assert exc.last_result == {"status": 503}
        assert exc.last_exception is None
    else:
        raise AssertionError("expected RetryExhaustedError")


def test_celery_public_exports_stable() -> None:
    assert celery_contrib.__all__ == [
        "ExecuteKwargsProvider",
        "ExecutePolicyLike",
        "OperationBuilder",
        "RetryKwargsProvider",
        "TaskLike",
        "default_operation",
        "default_retry_kwargs",
        "defer_sleep",
        "execute_task_with_retry",
    ]
