from collections.abc import Awaitable, Callable
from typing import Any

from .context import _AsyncPolicyContext, _PolicyContext
from .retry import AsyncRetry, Retry
from .types import LogHook, MetricHook, T


class Policy:
    """
    Unified resilience container with an optional retry component.
    """

    def __init__(self, *, retry: Retry | None = None) -> None:
        self.retry = retry

    def call(
        self,
        func: Callable[[], Any],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
    ) -> Any:
        if self.retry is None:
            return func()
        return self.retry.call(
            func,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
        )

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
    ) -> _PolicyContext:
        """
        Context manager that binds hooks/operation for multiple calls.
        """
        return _PolicyContext(self, on_metric, on_log, operation)


class AsyncPolicy:
    """
    Unified resilience container with an optional async retry component.
    """

    def __init__(self, *, retry: AsyncRetry | None = None) -> None:
        self.retry = retry

    async def call(
        self,
        func: Callable[[], Awaitable[T]],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
    ) -> T:
        if self.retry is None:
            return await func()
        return await self.retry.call(
            func,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
        )

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
    ) -> _AsyncPolicyContext:
        """
        Async context manager that binds hooks/operation for multiple calls.
        """
        return _AsyncPolicyContext(self, on_metric, on_log, operation)
