"""Testing utilities for deterministic policies and observability."""

from __future__ import annotations

import inspect
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar, cast

from ..circuit import CircuitState
from ..classify import default_classifier
from ..config import RetryConfig
from ..errors import ErrorClass, StopReason
from ..policy.types import RetryOutcome
from ..strategies import BackoffContext

T = TypeVar("T")

_MISSING = object()


@dataclass(frozen=True)
class CallRecord:
    func: Callable[[], Any]
    kwargs: dict[str, Any]
    result: Any | None = None
    exception: BaseException | None = None


@dataclass(frozen=True)
class ExecuteRecord:
    func: Callable[[], Any]
    kwargs: dict[str, Any]
    outcome: RetryOutcome[Any] | None = None
    exception: BaseException | None = None


@dataclass(frozen=True)
class BreakerDecision:
    allowed: bool
    state: CircuitState
    event: str | None = None


class FakeCircuitBreaker:
    """Simple, controllable circuit breaker stub for tests."""

    def __init__(
        self,
        *,
        state: CircuitState = CircuitState.CLOSED,
        allow_sequence: Sequence[BreakerDecision] | None = None,
        default_allowed: bool = True,
        default_event: str | None = None,
        success_event: str | None = None,
        failure_event: str | None = None,
    ) -> None:
        self._state = state
        self._allow_sequence = deque(allow_sequence or [])
        self.default_allowed = default_allowed
        self.default_event = default_event
        self.success_event = success_event
        self.failure_event = failure_event

        self.allow_calls = 0
        self.record_success_calls = 0
        self.record_cancel_calls = 0
        self.record_failure_calls: list[ErrorClass] = []

    @property
    def state(self) -> CircuitState:
        return self._state

    def allow(self) -> BreakerDecision:
        self.allow_calls += 1
        if self._allow_sequence:
            decision = self._allow_sequence.popleft()
            self._state = decision.state
            return decision
        return BreakerDecision(self.default_allowed, self._state, self.default_event)

    def record_success(self) -> str | None:
        self.record_success_calls += 1
        return self.success_event

    def record_failure(self, klass: ErrorClass) -> str | None:
        self.record_failure_calls.append(klass)
        return self.failure_event

    def record_cancel(self) -> None:
        self.record_cancel_calls += 1

    def push_decision(self, decision: BreakerDecision) -> None:
        self._allow_sequence.append(decision)


@dataclass
class DeterministicStrategy:
    """Deterministic backoff for tests.

    Returns values from ``sleeps`` based on attempt number (1-based).
    If attempts exceed the list, returns ``default`` when provided, or
    the last value in the list.
    """

    sleeps: Sequence[float]
    default: float | None = None
    calls: list[BackoffContext] = field(default_factory=list)

    def __call__(self, ctx: BackoffContext) -> float:
        self.calls.append(ctx)
        index = ctx.attempt - 1
        if index < len(self.sleeps):
            return float(self.sleeps[index])
        if self.default is not None:
            return float(self.default)
        if self.sleeps:
            return float(self.sleeps[-1])
        return 0.0

    def reset(self) -> None:
        self.calls.clear()


def instant_retries(_: BackoffContext) -> float:
    """Zero-sleep strategy for fast, deterministic retries in tests."""

    return 0.0


def no_retries(*, deadline_s: float = 60.0, attempt_timeout_s: float | None = None) -> RetryConfig:
    """Return a RetryConfig with retries disabled (max_attempts=1)."""

    return RetryConfig(
        deadline_s=deadline_s,
        attempt_timeout_s=attempt_timeout_s,
        max_attempts=1,
        max_unknown_attempts=0,
        default_strategy=instant_retries,
    )


class FakePolicy:
    """Policy stub for tests with configurable outcomes."""

    def __init__(
        self,
        *,
        call_result: Any = _MISSING,
        call_error: BaseException | None = None,
        execute_outcome: RetryOutcome[Any] | None = None,
    ) -> None:
        self.call_result = call_result
        self.call_error = call_error
        self.execute_outcome = execute_outcome
        self.calls: list[CallRecord] = []
        self.executions: list[ExecuteRecord] = []

    def _resolve_call(self, func: Callable[[], T]) -> T:
        if self.call_error is not None:
            raise self.call_error
        if self.call_result is not _MISSING:
            return cast(T, self.call_result)
        return func()

    def call(self, func: Callable[[], T], **kwargs: Any) -> T:
        kwargs_copy = dict(kwargs)
        try:
            result = self._resolve_call(func)
        except BaseException as exc:
            self.calls.append(CallRecord(func=func, kwargs=kwargs_copy, exception=exc))
            raise
        self.calls.append(CallRecord(func=func, kwargs=kwargs_copy, result=result))
        return result

    def execute(self, func: Callable[[], T], **kwargs: Any) -> RetryOutcome[T]:
        kwargs_copy = dict(kwargs)
        if self.execute_outcome is not None:
            preset_outcome = self.execute_outcome
            self.executions.append(
                ExecuteRecord(func=func, kwargs=kwargs_copy, outcome=preset_outcome)
            )
            return preset_outcome

        try:
            result = self._resolve_call(func)
        except Exception as exc:
            error_outcome: RetryOutcome[T] = RetryOutcome(
                ok=False,
                value=None,
                stop_reason=StopReason.MAX_ATTEMPTS_GLOBAL,
                attempts=1,
                last_class=default_classifier(exc),
                last_exception=exc,
                last_result=None,
                cause="exception",
                elapsed_s=0.0,
            )
            self.executions.append(
                ExecuteRecord(func=func, kwargs=kwargs_copy, outcome=error_outcome)
            )
            return error_outcome

        success_outcome: RetryOutcome[T] = RetryOutcome(
            ok=True,
            value=result,
            stop_reason=None,
            attempts=1,
            last_class=None,
            last_exception=None,
            last_result=None,
            cause=None,
            elapsed_s=0.0,
        )
        self.executions.append(
            ExecuteRecord(func=func, kwargs=kwargs_copy, outcome=success_outcome)
        )
        return success_outcome

    def context(self, **kwargs: Any) -> "_PolicyContext":
        return _PolicyContext(self, kwargs)


class RecordingPolicy:
    """Wrap a policy and record call/execute arguments and outcomes."""

    def __init__(self, policy: Any) -> None:
        self.policy = policy
        self.calls: list[CallRecord] = []
        self.executions: list[ExecuteRecord] = []

    def call(self, func: Callable[[], T], **kwargs: Any) -> Any:
        kwargs_copy = dict(kwargs)
        try:
            result = self.policy.call(func, **kwargs)
        except BaseException as exc:
            self.calls.append(CallRecord(func=func, kwargs=kwargs_copy, exception=exc))
            raise

        if inspect.isawaitable(result):

            async def _await_and_record() -> Any:
                try:
                    value = await result
                except BaseException as exc:
                    self.calls.append(CallRecord(func=func, kwargs=kwargs_copy, exception=exc))
                    raise
                self.calls.append(CallRecord(func=func, kwargs=kwargs_copy, result=value))
                return value

            return _await_and_record()

        self.calls.append(CallRecord(func=func, kwargs=kwargs_copy, result=result))
        return result

    def execute(self, func: Callable[[], T], **kwargs: Any) -> Any:
        kwargs_copy = dict(kwargs)
        try:
            outcome = self.policy.execute(func, **kwargs)
        except BaseException as exc:
            self.executions.append(ExecuteRecord(func=func, kwargs=kwargs_copy, exception=exc))
            raise

        if inspect.isawaitable(outcome):

            async def _await_and_record() -> Any:
                try:
                    value = await outcome
                except BaseException as exc:
                    self.executions.append(
                        ExecuteRecord(func=func, kwargs=kwargs_copy, exception=exc)
                    )
                    raise
                self.executions.append(
                    ExecuteRecord(func=func, kwargs=kwargs_copy, outcome=value)
                )
                return value

            return _await_and_record()

        self.executions.append(ExecuteRecord(func=func, kwargs=kwargs_copy, outcome=outcome))
        return outcome

    def context(self, **kwargs: Any) -> "_PolicyContext":
        return _PolicyContext(self, kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.policy, name)


class _PolicyContext:
    def __init__(self, policy: Any, kwargs: dict[str, Any]) -> None:
        self._policy = policy
        self._kwargs = kwargs

    def __enter__(self) -> Callable[..., Any]:
        return self.call

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False

    async def __aenter__(self) -> Callable[..., Any]:
        return self.call

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return self._policy.call(lambda: func(*args, **kwargs), **self._kwargs)


__all__ = [
    "BreakerDecision",
    "CallRecord",
    "DeterministicStrategy",
    "ExecuteRecord",
    "FakeCircuitBreaker",
    "FakePolicy",
    "RecordingPolicy",
    "instant_retries",
    "no_retries",
]
