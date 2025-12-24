"""
Async httpx example using AsyncRetryPolicy.

Run with:
    uv pip install httpx
    uv run python docs/snippets/httpx_async_retry.py
"""

import asyncio
from typing import Any

import httpx

from redress import AsyncRetryPolicy, default_classifier
from redress.errors import ErrorClass
from redress.strategies import decorrelated_jitter


def log_metric(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
    print(f"[metric] event={event} attempt={attempt} sleep_s={sleep_s:.3f} tags={tags}")


def build_policy() -> AsyncRetryPolicy:
    return AsyncRetryPolicy(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=2.0),
        strategies={
            ErrorClass.RATE_LIMIT: decorrelated_jitter(base_s=1.0, max_s=8.0),
        },
        deadline_s=10.0,
        max_attempts=5,
    )


async def fetch(policy: AsyncRetryPolicy, url: str) -> httpx.Response:
    async def _call() -> httpx.Response:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response

    return await policy.call(_call, on_metric=log_metric, operation="httpx_async_fetch")


async def demo(urls: list[str]) -> None:
    policy = build_policy()
    for url in urls:
        try:
            response = await fetch(policy, url)
            print(f"OK {url} -> {response.status_code}")
        except Exception as exc:  # noqa: BLE001 - demo code
            print(f"FAILED {url}: {exc}")


async def main() -> None:
    await demo(
        [
            "https://httpbin.org/status/500",
            "https://httpbin.org/status/429",
            "https://httpbin.org/status/200",
        ]
    )


if __name__ == "__main__":
    asyncio.run(main())
