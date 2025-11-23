# reflexio

![CI](https://github.com/aponysus/reflexio/actions/workflows/ci.yml/badge.svg)
![Coverage](https://codecov.io/gh/aponysus/reflexio/branch/master/graph/badge.svg)

Composable, low-overhead retry policies with **pluggable classification**, **per-class backoff strategies**, and **structured observability hooks**.  
Designed for services that need predictable retry behavior and clean integration with metrics/logging.

## Installation

Not published yet. Install locally:

```bash
uv pip install .
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

## Examples

- Sync httpx demo: `uv pip install httpx` then `uv run python examples/httpx_sync_retry.py`
- Async httpx demo using `AsyncRetryPolicy`: `uv pip install httpx` then `uv run python examples/httpx_async_retry.py`
- Async worker loop with retries: `uv run python examples/async_worker_retry.py`
- FastAPI proxy with metrics counter: `uv pip install "fastapi[standard]" httpx` then `uv run uvicorn examples.fastapi_downstream:app --reload`

## Versioning

Semantic Versioning.
