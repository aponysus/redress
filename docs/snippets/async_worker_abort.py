"""
Async worker with cooperative abort and durable attempt logging.

Run with:
    uv run python docs/snippets/async_worker_abort.py
"""

import asyncio
from typing import Any

from redress import AbortRetryError, AsyncPolicy, AsyncRetry, default_classifier
from redress.strategies import decorrelated_jitter


def record_attempt(event: str, fields: dict[str, Any]) -> None:
    # Replace this with a durable store (DB, queue, log sink) in production.
    print(f"[attempt] event={event} fields={fields}")


def log_event(event: str, fields: dict[str, Any]) -> None:
    record_attempt(event, fields)


def build_policy() -> AsyncPolicy:
    return AsyncPolicy(
        retry=AsyncRetry(
            classifier=default_classifier,
            strategy=decorrelated_jitter(max_s=1.0),
            deadline_s=6.0,
            max_attempts=4,
        )
    )


async def process_message(message: str, seen: dict[str, int]) -> str:
    seen[message] = seen.get(message, 0) + 1
    if message == "flaky" and seen[message] < 3:
        raise ConnectionError("transient network hiccup")
    await asyncio.sleep(0.05)
    return f"processed {message}"


async def worker_loop(messages: list[str], shutdown: asyncio.Event) -> None:
    policy = build_policy()
    seen: dict[str, int] = {}
    async with policy.context(
        on_log=log_event,
        operation="worker.process",
        abort_if=shutdown.is_set,
    ) as call:
        for msg in messages:
            try:
                result = await call(process_message, msg, seen)
                print(result)
            except AbortRetryError:
                print("shutdown requested, stopping worker")
                return
            except Exception as exc:  # noqa: BLE001 - demo code
                print(f"message {msg!r} failed permanently: {exc}")


async def main() -> None:
    shutdown = asyncio.Event()

    async def trigger_shutdown() -> None:
        await asyncio.sleep(0.6)
        shutdown.set()

    asyncio.create_task(trigger_shutdown())
    await worker_loop(["ok", "flaky", "ok", "flaky"], shutdown)


if __name__ == "__main__":
    asyncio.run(main())
