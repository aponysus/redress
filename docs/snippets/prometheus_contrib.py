"""
Prometheus contrib hook example.

Run with:
    uv pip install "redress[prometheus]"
    uv run python docs/snippets/prometheus_contrib.py
"""

from prometheus_client import Counter, Histogram

from redress import RetryPolicy, default_classifier
from redress.contrib.prometheus import prometheus_hooks
from redress.strategies import decorrelated_jitter

event_counter = Counter(
    "redress_events_total",
    "redress retry lifecycle events",
    ["event", "class", "operation"],
)
retry_sleep = Histogram(
    "redress_retry_sleep_seconds",
    "scheduled retry delays",
    ["class", "operation"],
)

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=1.0),
    max_attempts=3,
)

hooks = prometheus_hooks(events=event_counter, retry_sleep_seconds=retry_sleep)


def flaky() -> str:
    raise ConnectionError("boom")


try:
    policy.call(flaky, **hooks, operation="sync_user")
except Exception:
    pass
