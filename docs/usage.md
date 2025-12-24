# redress usage patterns

## Per-class strategies and limits

```python
from redress.policy import RetryPolicy
from redress.errors import ErrorClass
from redress.classify import default_classifier
from redress.strategies import decorrelated_jitter, equal_jitter

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=10.0),  # default for most classes
    strategies={
        ErrorClass.CONCURRENCY: decorrelated_jitter(max_s=1.0),
        ErrorClass.RATE_LIMIT: decorrelated_jitter(max_s=60.0),
        ErrorClass.SERVER_ERROR: equal_jitter(max_s=30.0),
    },
    per_class_max_attempts={
        ErrorClass.RATE_LIMIT: 3,
        ErrorClass.SERVER_ERROR: 5,
    },
)
```

## Using `operation` to distinguish call sites

```python
def fetch_profile():
    ...

policy.call(fetch_profile, operation="fetch_profile")
```

Metrics/logs include `operation=fetch_profile`, letting you split dashboards per call site.

## RetryConfig for shared settings

```python
from redress.config import RetryConfig
from redress.policy import RetryPolicy
from redress.classify import default_classifier

cfg = RetryConfig(
    deadline_s=45.0,
    max_attempts=6,
    per_class_max_attempts={
        ErrorClass.RATE_LIMIT: 2,
        ErrorClass.SERVER_ERROR: 4,
    },
)

policy = RetryPolicy.from_config(cfg, classifier=default_classifier)
```

## Async usage

`AsyncRetryPolicy` mirrors the sync API but awaits your callable and uses `asyncio.sleep` for backoff.

```python
import asyncio
from redress import AsyncRetryPolicy, default_classifier
from redress.errors import ErrorClass
from redress.strategies import decorrelated_jitter

async_policy = AsyncRetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=2.0),
    strategies={ErrorClass.RATE_LIMIT: decorrelated_jitter(min_s=1.0, max_s=8.0)},
    deadline_s=10.0,
    max_attempts=5,
)

async def fetch_user() -> str:
    ...

asyncio.run(async_policy.call(fetch_user, operation="fetch_user"))
```

Observability hooks (`on_metric`, `on_log`), deadlines, and per-class limits behave the same as the sync policy.

## Logging and metrics hooks together

```python
from redress.metrics import prometheus_metric_hook

def log_hook(event: str, fields: dict) -> None:
    logger.info("retry_event", extra={"event": event, **fields})

policy.call(
    lambda: do_work(),
    on_metric=prometheus_metric_hook(counter),
    on_log=log_hook,
    operation="sync_account",
)
```

## Decorator-based retries (sync + async)

The `retry` decorator wraps functions and chooses the right policy automatically based on whether the function is sync or async.

```python
from redress import retry, default_classifier
from redress.strategies import decorrelated_jitter

@retry  # defaults to default_classifier + decorrelated_jitter(max_s=5.0)
def fetch_user():
    ...

@retry
async def fetch_user_async():
    ...
```

Hooks and `operation` can be set on the decorator. The `operation` defaults to the function name when omitted.

## Context managers for repeated calls

You can bind hooks/operation once and reuse:

```python
policy = RetryPolicy(..., classifier=default_classifier, strategy=decorrelated_jitter())

with policy.context(operation="batch") as retry:
    retry(do_thing)
    retry(do_other, arg1, arg2)
```

Async variant:

```python
async with async_policy.context(operation="batch") as retry:
    await retry(do_async_work)
```

## Helper classifiers

`redress.extras` provides domain-oriented classifiers:

- `http_classifier` – maps HTTP status codes (e.g., 429→RATE_LIMIT, 500→SERVER_ERROR, 408→TRANSIENT).
- `sqlstate_classifier` – maps SQLSTATE codes (e.g., 40001/40P01→CONCURRENCY, HYT00/08xxx→TRANSIENT, 28xxx→AUTH).

## PyODBC classification example

`redress` stays dependency-free, so database-specific classifiers live in docs. See `docs/snippets/pyodbc_classifier.py` for a SQLSTATE-based mapper.

```python
from redress import retry
from redress.strategies import decorrelated_jitter
from docs.snippets.pyodbc_classifier import pyodbc_classifier  # adjust import path as needed

@retry(
    classifier=pyodbc_classifier,
    strategy=decorrelated_jitter(max_s=3.0),
    strategies={},  # optional per-class overrides
)
def run_query():
    ...
```
