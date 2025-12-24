"""
Simulated async worker that retries processing messages.

Run with:
    uv run python docs/snippets/async_worker_retry.py
"""

import asyncio
from typing import Any

from redress import AsyncRetryPolicy, default_classifier
from redress.errors import ErrorClass
from redress.strategies import decorrelated_jitter


def log_metric(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
    print(f"[metric] event={event} attempt={attempt} sleep_s={sleep_s:.3f} tags={tags}")


def build_policy() -> AsyncRetryPolicy:
    return AsyncRetryPolicy(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=1.0),
        strategies={ErrorClass.RATE_LIMIT: decorrelated_jitter(base_s=0.2, max_s=2.0)},
        deadline_s=5.0,
        max_attempts=4,
    )


async def process_message(message: str, seen: dict[str, int]) -> str:
    """
    Fake processor that fails the first two times for a specific message.
    """
    seen[message] = seen.get(message, 0) + 1
    if message == "flaky" and seen[message] < 3:
        raise ConnectionError("transient network hiccup")
    await asyncio.sleep(0.05)
    return f"processed {message}"


async def worker_loop(messages: list[str]) -> None:
    policy = build_policy()
    seen: dict[str, int] = {}
    for msg in messages:

        async def call(message: str = msg) -> str:
            return await process_message(message, seen)

        try:
            result = await policy.call(call, on_metric=log_metric, operation="worker_process")
            print(result)
        except Exception as exc:  # noqa: BLE001 - demo code
            print(f"Message {msg!r} failed permanently: {exc}")


async def main() -> None:
    await worker_loop(["ok", "flaky", "ok"])


if __name__ == "__main__":
    asyncio.run(main())
