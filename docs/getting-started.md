# Getting started

## Installation

```bash
uv pip install redress
# or
pip install redress
```

## Quick start (sync, canonical API)

```python
from redress import Policy, Retry, default_classifier
from redress.strategies import decorrelated_jitter

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),
        max_attempts=5,
        deadline_s=30.0,
    ),
)

result = policy.call(lambda: do_work(), operation="sync_task")
```

`Policy(retry=Retry(...))` is the primary API. It is the shape to use when you
want a consistent model for retries, circuit breakers, shared hooks, and
structured outcomes.

## Quick start (async, canonical API)

```python
import asyncio

from redress import AsyncPolicy, AsyncRetry, default_classifier
from redress.strategies import decorrelated_jitter

policy = AsyncPolicy(
    retry=AsyncRetry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),
        max_attempts=5,
        deadline_s=30.0,
    ),
)

async def main() -> None:
    result = await policy.call(lambda: do_work_async(), operation="async_task")
    print(result)

asyncio.run(main())
```

## Convenience shortcuts

```python
from redress import RetryPolicy, default_classifier
from redress.strategies import decorrelated_jitter

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
)

result = policy.call(lambda: do_work(), operation="sync_task")
```

`RetryPolicy` and `AsyncRetryPolicy` are backward-compatible shortcuts for
retry-only flows. They are sugar for `Policy(retry=Retry(...))` and
`AsyncPolicy(retry=AsyncRetry(...))`.

## Decorator shortcut

```python
from redress import retry

@retry
def fetch_user():
    ...
```

Use the decorator when you want the smallest amount of setup. Move to
`Policy(...)` when you need circuit breakers, richer execution control, or
shared configuration across multiple calls.
