"""
Datadog contrib hook example.

Run with:
    uv pip install "redress[datadog]"
    uv run python docs/snippets/datadog_contrib.py
"""

from datadog import initialize, statsd

from redress import RetryPolicy, default_classifier
from redress.contrib.datadog import datadog_hooks
from redress.strategies import decorrelated_jitter

initialize()

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=1.0),
    max_attempts=3,
)

hooks = datadog_hooks(statsd=statsd, prefix="svc.redress", constant_tags=["env:dev"])


def flaky() -> str:
    raise ConnectionError("boom")


try:
    policy.call(flaky, **hooks, operation="sync_user")
except Exception:
    pass
