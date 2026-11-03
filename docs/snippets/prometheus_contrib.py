"""
Prometheus contrib hook example.

Run with:
    uv run --extra prometheus python docs/snippets/prometheus_contrib.py
"""

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

from redress import Policy, Retry, default_classifier
from redress.contrib.prometheus import prometheus_hooks

registry = CollectorRegistry()
event_counter = Counter(
    "redress_events_total",
    "redress retry lifecycle events",
    ["event", "class", "operation"],
    registry=registry,
)
retry_sleep = Histogram(
    "redress_retry_sleep_seconds",
    "scheduled retry delays",
    ["class", "operation"],
    registry=registry,
)

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=lambda ctx: 0.25,
        max_attempts=2,
        sleeper=lambda _: None,  # Skip waiting in this demonstration.
    )
)

hooks = prometheus_hooks(events=event_counter, retry_sleep_seconds=retry_sleep)
attempts = 0


def flaky() -> str:
    global attempts
    attempts += 1
    if attempts == 1:
        raise ConnectionError("temporarily unavailable")
    return "ok"


result = policy.call(flaky, **hooks, operation="sync_user")
print(generate_latest(registry).decode())
