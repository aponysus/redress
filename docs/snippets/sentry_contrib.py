"""
Sentry contrib hook example.

Run with:
    export SENTRY_DSN=...
    uv pip install "redress[sentry]"
    uv run python docs/snippets/sentry_contrib.py
"""

import os

import sentry_sdk

from redress import RetryPolicy, default_classifier
from redress.contrib.sentry import sentry_hooks
from redress.strategies import decorrelated_jitter

sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"))

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=1.0),
    max_attempts=3,
)

hooks = sentry_hooks(sentry=sentry_sdk)


def flaky() -> str:
    raise ConnectionError("boom")


try:
    policy.call(flaky, **hooks, operation="sync_user")
except Exception:
    pass
