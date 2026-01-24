# tests/test_context.py

import asyncio

from redress import (
    AsyncPolicy,
    AsyncRetry,
    AsyncRetryPolicy,
    Policy,
    Retry,
    RetryPolicy,
    default_classifier,
)
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


def test_retry_component_context() -> None:
    retry = Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=0.0),
    )

    events: list[str] = []

    def metric(event: str, attempt: int, sleep_s: float, tags: dict[str, object]) -> None:
        events.append(event)

    with retry.context(on_metric=metric, operation="op") as run:

        def succeed() -> str:
            return "ok"

        assert run(succeed) == "ok"

    assert "success" in events


def test_policy_context() -> None:
    policy = Policy(
        retry=Retry(
            classifier=default_classifier,
            strategy=decorrelated_jitter(max_s=0.0),
        )
    )

    events: list[str] = []

    def metric(event: str, attempt: int, sleep_s: float, tags: dict[str, object]) -> None:
        events.append(event)

    with policy.context(on_metric=metric, operation="op") as retry:

        def succeed() -> str:
            return "ok"

        assert retry(succeed) == "ok"

    assert "success" in events


def test_policy_call_without_retry() -> None:
    policy = Policy()

    def succeed() -> str:
        return "ok"

    assert policy.call(succeed) == "ok"


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


def test_async_retry_component_context() -> None:
    retry = AsyncRetry(
        classifier=lambda exc: ErrorClass.TRANSIENT,
        strategy=lambda attempt, klass, prev: 0.0,
    )

    events: list[str] = []

    def metric(event: str, attempt: int, sleep_s: float, tags: dict[str, object]) -> None:
        events.append(event)

    async def runner() -> None:
        async with retry.context(on_metric=metric, operation="op") as run:

            async def succeed() -> str:
                return "ok"

            assert await run(succeed) == "ok"

    asyncio.run(runner())
    assert "success" in events


def test_async_policy_context() -> None:
    policy = AsyncPolicy(
        retry=AsyncRetry(
            classifier=lambda exc: ErrorClass.TRANSIENT,
            strategy=lambda attempt, klass, prev: 0.0,
        )
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


def test_async_policy_call_without_retry() -> None:
    policy = AsyncPolicy()

    async def succeed() -> str:
        return "ok"

    assert asyncio.run(policy.call(succeed)) == "ok"
