# tests/test_context.py

import asyncio

from redress import AsyncRetryPolicy, RetryPolicy, default_classifier
from redress.errors import ErrorClass
from redress.strategies import decorrelated_jitter


def test_retry_policy_context() -> None:
    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=0.0),
    )

    events: list[str] = []

    def metric(event: str, attempt: int, sleep_s: float, tags: dict[str, object]) -> None:
        events.append(event)

    with policy.context(on_metric=metric, operation="op") as retry:

        def succeed() -> str:
            return "ok"

        assert retry(succeed) == "ok"

    assert "success" in events


def test_async_retry_policy_context() -> None:
    policy = AsyncRetryPolicy(
        classifier=lambda exc: ErrorClass.TRANSIENT,
        strategy=lambda attempt, klass, prev: 0.0,
    )

    events: list[str] = []

    def metric(event: str, attempt: int, sleep_s: float, tags: dict[str, object]) -> None:
        events.append(event)

    async def runner() -> None:
        async with policy.context(on_metric=metric, operation="op") as retry:

            async def succeed() -> str:
                return "ok"

            assert await retry(succeed) == "ok"

    asyncio.run(runner())
    assert "success" in events
