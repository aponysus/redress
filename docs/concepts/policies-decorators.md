# Policies & decorators

## Policies

`RetryPolicy` and `AsyncRetryPolicy` wrap sync/async callables:

```python
from redress import RetryPolicy, AsyncRetryPolicy, default_classifier
from redress.strategies import decorrelated_jitter

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
    deadline_s=60,
    max_attempts=6,
)

result = policy.call(lambda: do_work(), operation="sync_op")
```

Async mirrors the same API and uses `asyncio.sleep` under the hood.

Context managers let you reuse hooks/operation:

```python
with policy.context(operation="batch") as retry:
    retry(task1)
    retry(task2)
```

## Decorator

`@retry` auto-chooses sync/async policy and defaults to `default_classifier` + `decorrelated_jitter(max_s=5.0)`:

```python
from redress import retry

@retry
def fetch_user():
    ...

@retry
async def fetch_user_async():
    ...
```

You can override classifiers/strategies and hooks via decorator arguments.
