# Getting started

## Installation

```bash
uv pip install redress
# or
pip install redress
```

## Quick start (sync)

```python
from redress import retry

@retry  # default_classifier + decorrelated_jitter(max_s=5.0)
def fetch_user():
    ...
```

## Quick start (async)

```python
from redress import retry

@retry
async def fetch_user_async():
    ...
```

## Policies directly

```python
from redress import RetryPolicy, default_classifier
from redress.strategies import decorrelated_jitter

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
)

result = policy.call(lambda: do_work(), operation="sync_task")
```

Async has the same shape with `AsyncRetryPolicy`.
