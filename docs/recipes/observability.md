# Observability recipes (low-cardinality tags)

See also: [HTTP recipes](http.md), [DB recipes](db.md), [Worker recipes](workers.md).

Redress emits lifecycle events via `on_metric` and `on_log`. These hooks are designed
for metrics/logging without coupling to a specific backend.

## Recommended tags

**Do** (low-cardinality):
- `class` (ErrorClass)
- `operation` (stable operation name)
- `stop_reason`
- `cause` (`exception` or `result`)
- `event` (retry, success, deadline_exceeded, etc.)

**Don't** (high-cardinality):
- full URLs or query strings
- user IDs, request IDs, trace IDs
- raw SQL or exception messages
- stack traces

If you need detailed diagnostics, log them separately at debug level, not as tags.

## Copy/paste example

```python
from redress import Policy, Retry, default_classifier
from redress.strategies import decorrelated_jitter


def metric_hook(event: str, attempt: int, sleep_s: float, tags: dict[str, object]) -> None:
    # Keep tags low-cardinality.
    print(f"event={event} attempt={attempt} sleep_s={sleep_s:.3f} tags={tags}")

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=3.0),
    )
)

policy.call(do_work, on_metric=metric_hook, operation="worker_task")
```

## Stop reasons in execute()

If you need a structured stop reason, use `execute()` and inspect the outcome:

```python
outcome = policy.execute(do_work, operation="worker_task")
print(outcome.stop_reason)
```

`stop_reason` is intentionally low-cardinality (ABORTED, DEADLINE_EXCEEDED, SCHEDULED,
MAX_ATTEMPTS_EXCEEDED, etc.).
