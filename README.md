# reflexio

![CI](https://github.com/aponysus/reflexio/actions/workflows/ci.yml/badge.svg)
[![codecov](https://codecov.io/gh/aponysus/reflexio/branch/main/graph/badge.svg?token=OaQIP7hzAE)](https://codecov.io/gh/aponysus/reflexio)
[![PyPI Version](https://img.shields.io/pypi/v/reflexio.svg)](https://pypi.org/project/reflexio/)



Composable, low-overhead retry policies with **pluggable classification**, **per-class backoff strategies**, and **structured observability hooks**.  
Designed for services that need predictable retry behavior and clean integration with metrics/logging.

## Installation

From PyPI:

```bash
uv pip install reflexio
# or
pip install reflexio
```

## Quick Start

```python
from reflexio.policy import RetryPolicy
from reflexio.classify import default_classifier
from reflexio.strategies import decorrelated_jitter

policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=10.0),
)

def flaky():
    # your operation that may fail
    ...

result = policy.call(flaky)
```

### Decorator quick start

```python
from reflexio import retry, default_classifier
from reflexio.strategies import decorrelated_jitter

@retry  # defaults to default_classifier + decorrelated_jitter(max_s=5.0)
def fetch_user():
    ...

# Or customize classifier/strategies
@retry(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=3.0),
)
def fetch_user_custom():
    ...

# Context manager for repeated calls with shared hooks/operation
policy = RetryPolicy(classifier=default_classifier, strategy=decorrelated_jitter(max_s=3.0))
with policy.context(operation="batch") as retry:
    retry(fetch_user)
```

### Async quick start

```python
import asyncio
from reflexio import AsyncRetryPolicy, default_classifier
from reflexio.strategies import decorrelated_jitter

async_policy = AsyncRetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=5.0),
)

async def flaky_async():
    ...

asyncio.run(async_policy.call(flaky_async))
```

## Why reflexio?

Most retry libraries give you either:

- decorators with a fixed backoff model, or  
- one global strategy for all errors.

**reflexio** gives you something different:

### ✔ Exception → coarse error class mapping  
Provided via `default_classifier`.

### ✔ Per-class strategy dispatch  
Each `ErrorClass` can use its own backoff logic.

### ✔ Dependency-free strategies with jitter  
`decorrelated_jitter`, `equal_jitter`, `token_backoff`.

### ✔ Deadlines, max attempts, and separate caps for UNKNOWN  
Deterministic retry envelopes.

### ✔ Clean observability hook  

Single callback for:  
`success`, `retry`, `permanent_fail`, `deadline_exceeded`, `max_attempts_exceeded`, `max_unknown_attempts_exceeded`.

## Error Classes & Classification

```
PERMANENT
CONCURRENCY
RATE_LIMIT
SERVER_ERROR
TRANSIENT
UNKNOWN
```

Classification rules:

- Explicit reflexio error types  
- Numeric codes (`err.status` or `err.code`)  
- Name heuristics  
- Fallback to UNKNOWN  

## Metrics & Observability

```python
def metric_hook(event, attempt, sleep_s, tags):
    print(event, attempt, sleep_s, tags)

policy.call(my_op, on_metric=metric_hook)
```

## Backoff Strategies

Strategy signature:

```
(attempt: int, klass: ErrorClass, prev_sleep: Optional[float]) -> float
```

Built‑ins:

- `decorrelated_jitter()`
- `equal_jitter()`
- `token_backoff()`

## Per-Class Example

```python
policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=10.0),  # default
    strategies={
        ErrorClass.CONCURRENCY: decorrelated_jitter(max_s=1.0),
        ErrorClass.RATE_LIMIT: decorrelated_jitter(max_s=60.0),
        ErrorClass.SERVER_ERROR: equal_jitter(max_s=30.0),
    },
)
```

## Deadline & Attempt Controls

```python
policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(),
    deadline_s=60,
    max_attempts=8,
    max_unknown_attempts=2,
)
```

## Development

```bash
uv run pytest
```

## Examples (in `docs/snippets/`)

- Sync httpx demo: `uv pip install httpx` then `uv run python docs/snippets/httpx_sync_retry.py`
- Async httpx demo using `AsyncRetryPolicy`: `uv pip install httpx` then `uv run python docs/snippets/httpx_async_retry.py`
- Async worker loop with retries: `uv run python docs/snippets/async_worker_retry.py`
- Decorator usage (sync + async): `uv run python docs/snippets/decorator_retry.py`
- FastAPI proxy with metrics counter: `uv pip install "fastapi[standard]" httpx` then `uv run uvicorn docs.snippets.fastapi_downstream:app --reload`
- FastAPI middleware with per-endpoint policies: `uv pip install "fastapi[standard]" httpx` then `uv run uvicorn docs.snippets.fastapi_middleware:app --reload`
- PyODBC + SQLSTATE classification example: `uv pip install pyodbc` then `uv run python docs/snippets/pyodbc_retry.py`
- requests example: `uv pip install requests` then `uv run python docs/snippets/requests_retry.py`
- asyncpg example: `uv pip install asyncpg` and set `ASYNC_PG_DSN`, then `uv run python docs/snippets/asyncpg_retry.py`
- Pyperf microbenchmarks: `uv pip install .[dev]` then `uv run python docs/snippets/bench_retry.py`

## Docs site

- Build/serve locally: `uv pip install .[docs]` then `uv run mkdocs serve`
- Pages: `docs/index.md`, `docs/usage.md`, `docs/observability.md`, `docs/recipes.md` with runnable snippets in `docs/snippets/`.

## Versioning

Semantic Versioning.
