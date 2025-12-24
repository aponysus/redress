"""
Requests example demonstrating redress usage.

Run with:
    uv pip install requests
    uv run python docs/snippets/requests_retry.py
"""

import requests

from redress import RetryPolicy
from redress.extras import http_classifier
from redress.strategies import decorrelated_jitter


def log_metric(event: str, attempt: int, sleep_s: float, tags: dict[str, object]) -> None:
    print(f"[metric] event={event} attempt={attempt} sleep_s={sleep_s:.3f} tags={tags}")


def build_policy() -> RetryPolicy:
    return RetryPolicy(
        classifier=http_classifier,
        strategy=decorrelated_jitter(max_s=2.0),
        strategies={
            # Longer backoff for rate limits
            # Reuses the same classifier; status 429 -> RATE_LIMIT
        },
        deadline_s=8.0,
        max_attempts=4,
    )


def fetch(policy: RetryPolicy, url: str) -> requests.Response:
    def _call() -> requests.Response:
        resp = requests.get(url, timeout=3.0)
        resp.raise_for_status()
        return resp

    return policy.call(_call, on_metric=log_metric, operation="requests_fetch")


def demo(urls: list[str]) -> None:
    policy = build_policy()
    for url in urls:
        try:
            resp = fetch(policy, url)
            print(f"OK {url} -> {resp.status_code}")
        except Exception as exc:  # noqa: BLE001 - demo code
            print(f"FAILED {url}: {exc}")


if __name__ == "__main__":
    demo(
        [
            "https://httpbin.org/status/500",
            "https://httpbin.org/status/429",
            "https://httpbin.org/status/200",
        ]
    )
