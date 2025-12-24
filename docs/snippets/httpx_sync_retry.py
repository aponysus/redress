"""
Synchronous httpx example demonstrating redress usage.

Run with:
    uv run python docs/snippets/httpx_sync_retry.py
"""

from collections.abc import Iterable
from typing import Any

import httpx

from redress import RetryPolicy, default_classifier
from redress.errors import ErrorClass
from redress.strategies import decorrelated_jitter


def log_metric(event: str, attempt: int, sleep_s: float, tags: dict[str, Any]) -> None:
    """
    Lightweight metric hook that just prints what would be emitted.
    """
    print(f"[metric] event={event} attempt={attempt} sleep_s={sleep_s:.3f} tags={tags}")


def build_policy() -> RetryPolicy:
    """
    Configure a RetryPolicy with a default strategy and a special case for rate limits.
    """
    return RetryPolicy(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=2.0),
        strategies={
            ErrorClass.RATE_LIMIT: decorrelated_jitter(base_s=1.0, max_s=8.0),
        },
        deadline_s=10.0,
        max_attempts=5,
    )


def fetch(policy: RetryPolicy, url: str) -> httpx.Response:
    """
    Execute a GET request with retries applied.
    """

    def _call() -> httpx.Response:
        response = httpx.get(url, timeout=5.0)
        response.raise_for_status()
        return response

    return policy.call(_call, on_metric=log_metric, operation="httpx_sync_fetch")


def demo(urls: Iterable[str]) -> None:
    policy = build_policy()
    for url in urls:
        try:
            response = fetch(policy, url)
            print(f"OK {url} -> {response.status_code}")
        except Exception as exc:  # noqa: BLE001 - demo code
            print(f"FAILED {url}: {exc}")


if __name__ == "__main__":
    demo(
        [
            "https://httpbin.org/status/500",  # will trigger retries, then fail
            "https://httpbin.org/status/429",  # rate limit strategy
            "https://httpbin.org/status/200",
        ]
    )
