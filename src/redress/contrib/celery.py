"""Celery integration helpers.

This module stays dependency-light by using protocols instead of importing
Celery directly. It routes task execution through ``policy.execute(...)`` with
deferred sleeps, then translates scheduled outcomes into ``task.retry(...)``.
"""

from collections.abc import Callable, Mapping
from typing import Any, Protocol, TypeVar, cast

from ..errors import RetryExhaustedError, StopReason
from ..policy.types import RetryOutcome
from ..sleep import SleepDecision
from ..strategies import BackoffContext

T = TypeVar("T")


class TaskLike(Protocol):
    name: str | None

    def retry(self, **kwargs: Any) -> Any: ...


class ExecutePolicyLike(Protocol[T]):
    def execute(self, func: Callable[[], T], **kwargs: Any) -> RetryOutcome[T]: ...


OperationBuilder = Callable[[TaskLike], str | None]
ExecuteKwargsProvider = Callable[[TaskLike], Mapping[str, Any]]
RetryKwargsProvider = Callable[[RetryOutcome[Any], TaskLike], Mapping[str, Any]]


def defer_sleep(_: BackoffContext, __: float) -> SleepDecision:
    """
    Tell redress to defer retry scheduling to the caller.
    """
    return SleepDecision.DEFER


def default_operation(task: TaskLike) -> str:
    """
    Build a low-cardinality operation name for a task.
    """
    name = getattr(task, "name", None)
    if isinstance(name, str) and name:
        return name
    task_type = type(task)
    module = getattr(task_type, "__module__", None)
    qualname = getattr(task_type, "__qualname__", task_type.__name__)
    if isinstance(module, str) and module:
        return f"{module}.{qualname}"
    return qualname


def default_retry_kwargs(outcome: RetryOutcome[Any], _task: TaskLike) -> dict[str, Any]:
    """
    Build default ``task.retry(...)`` kwargs from a scheduled outcome.
    """
    kwargs: dict[str, Any] = {}
    if outcome.next_sleep_s is not None:
        kwargs["countdown"] = outcome.next_sleep_s
    if outcome.last_exception is not None:
        kwargs["exc"] = outcome.last_exception
    return kwargs


def _resolve_operation(
    operation: str | OperationBuilder | None,
    task: TaskLike,
) -> str | None:
    if operation is None:
        return default_operation(task)
    if callable(operation):
        return operation(task)
    return operation


def _resolve_execute_kwargs(
    execute_kwargs: Mapping[str, Any] | ExecuteKwargsProvider | None,
    task: TaskLike,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if execute_kwargs is None:
        return kwargs
    if callable(execute_kwargs):
        kwargs.update(execute_kwargs(task))
    else:
        kwargs.update(execute_kwargs)
    return kwargs


def _resolve_retry_kwargs(
    retry_kwargs: Mapping[str, Any] | RetryKwargsProvider | None,
    outcome: RetryOutcome[Any],
    task: TaskLike,
) -> dict[str, Any]:
    kwargs = default_retry_kwargs(outcome, task)
    if retry_kwargs is None:
        return kwargs
    overrides = retry_kwargs(outcome, task) if callable(retry_kwargs) else retry_kwargs
    kwargs.update(overrides)
    return kwargs


def execute_task_with_retry(
    task: TaskLike,
    policy: ExecutePolicyLike[T],
    func: Callable[[], T],
    *,
    operation: str | OperationBuilder | None = None,
    execute_kwargs: Mapping[str, Any] | ExecuteKwargsProvider | None = None,
    retry_kwargs: Mapping[str, Any] | RetryKwargsProvider | None = None,
) -> T:
    """
    Execute a bound Celery task body through ``policy.execute(...)``.

    Successful outcomes return their value. Scheduled outcomes call
    ``task.retry(...)`` with a default ``countdown`` and ``exc`` when available.
    Terminal failures re-raise the last exception or raise ``RetryExhaustedError``
    when the failure was result-based.
    """
    kwargs = _resolve_execute_kwargs(execute_kwargs, task)
    if "sleep" not in kwargs:
        kwargs["sleep"] = defer_sleep
    if "operation" not in kwargs:
        operation_value = _resolve_operation(operation, task)
        if operation_value is not None:
            kwargs["operation"] = operation_value

    outcome = policy.execute(func, **kwargs)
    if outcome.ok:
        return cast(T, outcome.value)

    if outcome.stop_reason is StopReason.SCHEDULED:
        return cast(T, task.retry(**_resolve_retry_kwargs(retry_kwargs, outcome, task)))

    if outcome.last_exception is not None:
        raise outcome.last_exception

    raise RetryExhaustedError(
        stop_reason=outcome.stop_reason or StopReason.MAX_ATTEMPTS_GLOBAL,
        attempts=outcome.attempts,
        last_class=outcome.last_class,
        last_exception=None,
        last_result=outcome.last_result,
        next_sleep_s=outcome.next_sleep_s,
    ) from None


__all__ = [
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
