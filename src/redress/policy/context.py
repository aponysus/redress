from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, TYPE_CHECKING, cast

from .types import LogHook, MetricHook, T

if TYPE_CHECKING:
    from .container import AsyncPolicy, Policy
    from .retry import AsyncRetry, Retry


@dataclass
class _RetryContext:
    policy: "Retry"
    on_metric: MetricHook | None
    on_log: LogHook | None
    operation: str | None

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
        )
        return cast(T, result)


@dataclass
class _AsyncRetryContext:
    policy: "AsyncRetry"
    on_metric: MetricHook | None
    on_log: LogHook | None
    operation: str | None

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
        )
        return result


@dataclass
class _PolicyContext:
    policy: "Policy"
    on_metric: MetricHook | None
    on_log: LogHook | None
    operation: str | None

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
        )
        return cast(T, result)


@dataclass
class _AsyncPolicyContext:
    policy: "AsyncPolicy"
    on_metric: MetricHook | None
    on_log: LogHook | None
    operation: str | None

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
        )
        return result
