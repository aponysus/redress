# redress

![CI](https://github.com/aponysus/redress/actions/workflows/ci.yml/badge.svg)
[![codecov](https://codecov.io/gh/aponysus/redress/branch/main/graph/badge.svg?token=OaQIP7hzAE)](https://codecov.io/gh/aponysus/redress)
[![PyPI Version](https://img.shields.io/pypi/v/redress.svg)](https://pypi.org/project/redress/)
[![Docs](https://img.shields.io/github/actions/workflow/status/aponysus/redress/docs.yml?label=docs)](https://aponysus.github.io/redress/)
[![Bench](https://img.shields.io/github/actions/workflow/status/aponysus/redress/ci.yml?label=bench)](https://github.com/aponysus/redress/actions/workflows/ci.yml)


> redress (v.): to remedy or to set right.

Policy-driven failure handling for Python services.

redress treats retries, circuit breakers, and stop conditions as coordinated responses to classified failure—making failure behavior explicit, bounded, and observable.

## Why redress?

Most failure-handling code grows organically around retries, circuit breakers, and ad-hoc rules. redress starts from a different premise: failure handling is policy.

**Classify, then dispatch.** Exceptions get mapped to semantic error classes (RATE_LIMIT, TRANSIENT, SERVER_ERROR, etc.), and each class can have its own backoff strategy. Rate limits back off aggressively; transient blips retry fast.

```python
policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),  # default fallback
        strategies={
            ErrorClass.RATE_LIMIT: decorrelated_jitter(max_s=60.0),
            ErrorClass.TRANSIENT: decorrelated_jitter(max_s=1.0),
        },
    ),
)
```

**Single observability hook.** One callback for success, retry, permanent failure, deadline exceeded—plug it into your metrics/logging and always know why retries stopped.

**Circuit breaking.** Policies can open a circuit after repeated failures, failing fast instead of piling up retries. Retries and circuit breakers are treated as policy responses to classified failure, not separate mechanisms.

**Sync/async symmetry.** `Policy` and `AsyncPolicy` share the same API and configuration; `RetryPolicy` / `AsyncRetryPolicy` remain convenient shortcuts.

**Optional classifiers.** Extras for common libraries (aiohttp, grpc, boto3, redis, urllib3, pyodbc).

**Retry budgets.** Shared rolling-window limits to prevent retry storms across operations.


## Documentation

- Site: https://aponysus.github.io/redress/
- Getting started: https://aponysus.github.io/redress/getting-started/

## Installation

From PyPI:

```bash
uv pip install redress
# or
pip install redress
```

## Quick Start

```python
from redress import CircuitBreaker, ErrorClass, Policy, Retry, default_classifier
from redress.strategies import decorrelated_jitter

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),
        deadline_s=60,
        max_attempts=6,
    ),
    # Fail fast when the upstream is persistently unhealthy.
    circuit_breaker=CircuitBreaker(
        failure_threshold=5,
        window_s=60.0,
        recovery_timeout_s=30.0,
        trip_on={ErrorClass.SERVER_ERROR, ErrorClass.CONCURRENCY},
    ),
)

def flaky():
    # your operation that may fail
    ...

result = policy.call(flaky)

# RATE_LIMIT failures back off aggressively,
# TRANSIENT failures retry quickly,
# UNKNOWN failures are tightly capped.
```

### Decorator quick start

```python
from redress import retry, default_classifier
from redress.strategies import decorrelated_jitter

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
```
If you provide `strategies` without `strategy`, the decorator will not add a default
strategy.

```python
# Context manager for repeated calls with shared hooks/operation
with policy.context(operation="batch") as retry:
    retry(task1)
    retry(task2)
```

### Async quick start

```python
import asyncio
from redress import AsyncPolicy, AsyncRetry, default_classifier
from redress.strategies import decorrelated_jitter

async_policy = AsyncPolicy(
    retry=AsyncRetry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=5.0),
    ),
)

async def flaky_async():
    ...

asyncio.run(async_policy.call(flaky_async))
```

## Error Classes & Classification

```
AUTH
PERMISSION
PERMANENT
CONCURRENCY
RATE_LIMIT
SERVER_ERROR
TRANSIENT
UNKNOWN
```

Redress intentionally keeps `ErrorClass` small and fixed. The goal is semantic
classification ("rate limit" vs. "server error") rather than mechanical mapping to
every exception type. If you need finer-grained behavior, use separate policies per
use case. Optional classification context can carry hints (for example, Retry-After)
without expanding the class set.

Classification rules:

- Explicit redress error types  
- Numeric codes (`err.status` or `err.code`)  
- Name heuristics  
- Fallback to UNKNOWN  

Name heuristics are a convenience for quick starts; for production, prefer a domain-specific
classifier (HTTP/DB/etc.) or `strict_classifier` to avoid surprises.

Classifiers can return `Classification(klass=..., retry_after_s=..., details=...)` to pass
structured hints to strategies. Returning `ErrorClass` is shorthand for
`Classification(klass=klass)`.

## Metrics & Observability

```python
def metric_hook(event, attempt, sleep_s, tags):
    print(event, attempt, sleep_s, tags)

policy.call(my_op, on_metric=metric_hook)
```

## Backoff Strategies

Strategy signature (context-aware):

```
(ctx: BackoffContext) -> float
```

Legacy signature (still supported):

```
(attempt: int, klass: ErrorClass, prev_sleep: Optional[float]) -> float
```

Built‑ins:

- `decorrelated_jitter()`
- `equal_jitter()`
- `token_backoff()`
- `retry_after_or(...)`

## Per-Class Example

```python
policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=10.0),  # default
        strategies={
            ErrorClass.CONCURRENCY: decorrelated_jitter(max_s=1.0),
            ErrorClass.RATE_LIMIT: decorrelated_jitter(max_s=60.0),
            ErrorClass.SERVER_ERROR: equal_jitter(max_s=30.0),
        },
    ),
)
```

## Deadline & Attempt Controls

```python
policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(),
        deadline_s=60,
        max_attempts=8,
        max_unknown_attempts=2,
    ),
)
```

## Development

```bash
uv run pytest
```

## CLI

- Lint a retry config or policy to catch obvious misconfigurations:

```python
# app_retry.py
from redress import RetryConfig
from redress.strategies import decorrelated_jitter

cfg = RetryConfig(
    default_strategy=decorrelated_jitter(max_s=1.5),
    max_attempts=5,
)
```

Then from the repo root or any env where app_retry is on PYTHONPATH:
```bash
redress doctor app_retry:cfg
# Show a normalized snapshot of active values:
redress doctor app_retry:cfg --show
```

`doctor` accepts `module:attribute` pointing to a `RetryConfig`, `Policy`/`AsyncPolicy`, `Retry`/`AsyncRetry`, or the `RetryPolicy`/`AsyncRetryPolicy` shortcuts. The attribute defaults to `config` if omitted (e.g., `myapp.settings` will look for `settings:config`).

Example `--show` output:

```
Config snapshot:
  source: app_retry:cfg
  deadline_s: 60.0
  max_attempts: 5
  max_unknown_attempts: 2
  default_strategy: redress.strategies.decorrelated_jitter.<locals>.f
  class_strategies:
    (none)
  per_class_max_attempts:
    (none)
OK: 'app_retry:cfg' passed config checks.
```

## Examples (in `docs/snippets/`)

- Sync httpx demo: `uv pip install httpx` then `uv run python docs/snippets/httpx_sync_retry.py`
- Async httpx demo: `uv pip install httpx` then `uv run python docs/snippets/httpx_async_retry.py`
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
