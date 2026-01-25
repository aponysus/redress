from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from ..sleep import SleepFn
from .types import AbortPredicate, AttemptHook, LogHook, MetricHook, T

if TYPE_CHECKING:
    from .async_policy import AsyncPolicy
    from .policy import Policy
    from .retry_async import AsyncRetry
    from .retry_sync import Retry


@dataclass
class _RetryContext:
    policy: "Retry"
    on_metric: MetricHook | None
    on_log: LogHook | None
    operation: str | None
    abort_if: AbortPredicate | None
    sleep: SleepFn | None
    on_attempt_start: AttemptHook | None
    on_attempt_end: AttemptHook | None

    def __enter__(self) -> Callable[..., T]:
        return self.call

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        result = self.policy.call(
            lambda: func(*args, **kwargs),
            on_metric=self.on_metric,
            on_log=self.on_log,
            operation=self.operation,
            abort_if=self.abort_if,
            sleep=self.sleep,
            on_attempt_start=self.on_attempt_start,
            on_attempt_end=self.on_attempt_end,
        )
        return cast(T, result)


@dataclass
class _AsyncRetryContext:
    policy: "AsyncRetry"
    on_metric: MetricHook | None
    on_log: LogHook | None
    operation: str | None
    abort_if: AbortPredicate | None
    sleep: SleepFn | None
    on_attempt_start: AttemptHook | None
    on_attempt_end: AttemptHook | None

    async def __aenter__(self) -> Callable[..., Awaitable[T]]:
        return self.call

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False

    async def call(self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        result = await self.policy.call(
            lambda: func(*args, **kwargs),
            on_metric=self.on_metric,
            on_log=self.on_log,
            operation=self.operation,
            abort_if=self.abort_if,
            sleep=self.sleep,
            on_attempt_start=self.on_attempt_start,
            on_attempt_end=self.on_attempt_end,
        )
        return result


@dataclass
class _PolicyContext:
    policy: "Policy"
    on_metric: MetricHook | None
    on_log: LogHook | None
    operation: str | None
    abort_if: AbortPredicate | None
    sleep: SleepFn | None
    on_attempt_start: AttemptHook | None
    on_attempt_end: AttemptHook | None

    def __enter__(self) -> Callable[..., T]:
        return self.call

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        result = self.policy.call(
            lambda: func(*args, **kwargs),
            on_metric=self.on_metric,
            on_log=self.on_log,
            operation=self.operation,
            abort_if=self.abort_if,
            sleep=self.sleep,
            on_attempt_start=self.on_attempt_start,
            on_attempt_end=self.on_attempt_end,
        )
        return cast(T, result)


@dataclass
class _AsyncPolicyContext:
    policy: "AsyncPolicy"
    on_metric: MetricHook | None
    on_log: LogHook | None
    operation: str | None
    abort_if: AbortPredicate | None
    sleep: SleepFn | None
    on_attempt_start: AttemptHook | None
    on_attempt_end: AttemptHook | None

    async def __aenter__(self) -> Callable[..., Awaitable[T]]:
        return self.call

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False

    async def call(self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        result = await self.policy.call(
            lambda: func(*args, **kwargs),
            on_metric=self.on_metric,
            on_log=self.on_log,
            operation=self.operation,
            abort_if=self.abort_if,
            sleep=self.sleep,
            on_attempt_start=self.on_attempt_start,
            on_attempt_end=self.on_attempt_end,
        )
        return result
