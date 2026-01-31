# Worker / queue retries

This recipe shows a simple worker loop with retries, backpressure via budgets,
and cooperative shutdown.

```python
import signal
import time

from redress import Budget, RetryPolicy, default_classifier
from redress.errors import StopReason
from redress.strategies import decorrelated_jitter

shutdown = {"now": False}

def handle_signal(*_args):
    shutdown["now"] = True

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

budget = Budget(max_retries=200, window_s=60.0)

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=2.0),
    max_attempts=5,
    deadline_s=10.0,
    budget=budget,
)


def fetch_job():
    # Replace with your queue client
    raise RuntimeError("transient")


def process_job(job):
    # Your business logic
    return None


while not shutdown["now"]:
    try:
        job = policy.call(fetch_job, operation="queue_fetch", abort_if=lambda: shutdown["now"])
    except Exception:
        # Backoff outside of redress to avoid tight loops when no work is available.
        time.sleep(0.1)
        continue

    outcome = policy.execute(lambda: process_job(job), operation="job_process")
    if outcome.stop_reason is StopReason.BUDGET_EXHAUSTED:
        # Optionally stop consuming or shed load until budget recovers.
        time.sleep(1.0)
```
