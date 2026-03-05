"""
HTTPX contrib helpers: sync + async request wrappers.

Run with:
    uv pip install "redress[httpx]"
    uv run python docs/snippets/httpx_contrib.py
"""

import asyncio

import httpx

from redress import AsyncRetryPolicy, RetryPolicy, default_classifier
from redress.contrib.httpx import (
    AsyncRetryingHttpxClient,
    RetryingHttpxClient,
    default_result_classifier,
    is_idempotent_method,
)
from redress.strategies import decorrelated_jitter, retry_after_or


def sync_demo() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, request=request, text="ok")

    policy = RetryPolicy(
        classifier=default_classifier,
        result_classifier=default_result_classifier,
        strategy=decorrelated_jitter(base_s=0.01, max_s=0.05),
        max_attempts=5,
        deadline_s=2.0,
    )

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        wrapped = RetryingHttpxClient(
            client,
            policy,
            skip_if=lambda method, _url: not is_idempotent_method(method),
        )
        response = wrapped.get("/flaky")
    print(f"sync status={response.status_code} attempts={attempts['count']}")


async def async_demo() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, request=request, text="ok")

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        result_classifier=default_result_classifier,
        strategy=retry_after_or(decorrelated_jitter(base_s=0.01, max_s=0.05), jitter_s=0.0),
        max_attempts=5,
        deadline_s=2.0,
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    ) as client:
        wrapped = AsyncRetryingHttpxClient(
            client,
            policy,
            skip_if=lambda method, _url: not is_idempotent_method(method),
        )
        response = await wrapped.get("/rate-limited")
    print(f"async status={response.status_code} attempts={attempts['count']}")


if __name__ == "__main__":
    sync_demo()
    asyncio.run(async_demo())
