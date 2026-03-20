# Background worker with bounded retries

Use this starter when you need a worker or queue consumer with bounded retries,
shared retry backpressure, and structured outcomes.

```python
from redress import Budget, Policy, Retry, StopReason, default_classifier
from redress.strategies import decorrelated_jitter

budget = Budget(max_retries=200, window_s=60.0)

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=2.0),
        max_attempts=5,
        deadline_s=10.0,
        budget=budget,
        max_unknown_attempts=2,
    ),
)

outcome = policy.execute(process_job, operation="worker.process")

if outcome.stop_reason is StopReason.BUDGET_EXHAUSTED:
    # Back off outside the retry loop and let the system recover.
    ...
```

Why these defaults:

- budgets prevent retry storms across many jobs
- `execute()` gives you a stop reason the worker can act on
- a short deadline keeps one bad job from dominating worker time
- unknown failures stay bounded instead of retrying indefinitely

For the core API surface, see [Usage](../usage.md). For broader queue and
shutdown patterns, see [Worker recipes](../recipes/workers.md).
